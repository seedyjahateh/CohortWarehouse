"""End-to-end acceptance drills on the 25-person fixture (PRD Sections 9.2, 9.4, 11.3, NFR-03/09/10, US-07/08).

Order matters: each test builds on the previous state. Requires a disposable database
(CW_TEST_DISPOSABLE_DB=1): the first test wipes and bootstraps the warehouse.
"""

from __future__ import annotations

import time

import psycopg
import pytest

from cohortwarehouse.errors import BuildError, PublicationError, QualityGateError
from cohortwarehouse.ingest import ingest
from cohortwarehouse.pipeline import run_pipeline
from cohortwarehouse.publish import publish, restore, validate_release
from cohortwarehouse.retention import cleanup
from tests.conftest import FIXTURE, patient_uuid, pseudo_id
from tests.integration.helpers import (
    eligible,
    env,
    expected_sets,
    memberships,
    query,
    reset_warehouse,
    snapshot_schema,
)

pytestmark = [pytest.mark.integration, pytest.mark.dbt]
STATE: dict = {}


def _assert_matches_expected(schema: str, expected: dict, batch: str, *, role: str = "admin") -> None:
    cohorts, eligible_expected = expected_sets(expected, batch)
    assert eligible(schema, role=role) == eligible_expected
    assert memberships(schema, role=role) == cohorts


def _patient_key(number: int) -> int:
    return query("select surrogate_id from ops.entity_key_map where entity_type = 'patient' and natural_key = %s",
                 (patient_uuid(number),))[0][0]


def test_01_ingest_baseline_quarantines_exactly_the_declared_rows(disposable_database, expected):
    reset_warehouse()
    result = ingest(FIXTURE / "batch_A" / "manifest.json")
    assert result.outcome == "loaded"
    actual = {(f, n, r) for f, n, r in query("select file_key, record_number, reason from ops.quarantine")}
    declared = {(q["file"], q["record_number"], q["reason"]) for q in expected["quarantine"]["fixture-A"]}
    assert actual == declared
    for parsed, accepted, quarantined in query(
            "select parsed_records, accepted_records, quarantined_records from ops.batch_file"):
        assert parsed == accepted + quarantined

    raw_rows_before = query("select count(*) from raw.observations")[0][0]
    assert ingest(FIXTURE / "batch_A" / "manifest.json").outcome == "already_loaded"
    assert query("select count(*) from raw.observations")[0][0] == raw_rows_before


def test_02_baseline_run_validates_and_matches_hand_derived_cohorts(disposable_database, expected):
    result = run_pipeline(batch_id="fixture-A")
    assert result["mode"] == "full_refresh"
    assert result["quality_gate"]["status"] == "validated"
    _assert_matches_expected("work_bi", expected, "fixture-A")
    tie = query("select patient_pseudo_id from work_bi.bi_patient_snapshot where systolic_tie_flag")
    assert {r[0] for r in tie} == {pseudo_id(n) for n in expected["after_batch"]["fixture-A"]["systolic_tie"]}
    STATE["run_A"] = result["run_id"]
    STATE["p01_key"] = _patient_key(1)


def test_02b_impossible_stop_is_nulled_ledgered_and_imputed_not_dropped(disposable_database, expected):
    nulled = query("select source_file, count(*) from work_omop.cw_exclusion_ledger "
                   "where reason = 'stop_before_start_nulled' and event_retained group by source_file")
    assert dict(nulled) == expected["exclusions"]["stop_before_start_nulled"]
    p06 = _patient_key(6)
    # The event survives in the star with no end value...
    assert query("select end_date_key, end_date from work_star.fct_medication where patient_key = %s", (p06,)) == [
        (0, None)]
    # ...and OMOP's required end date is the documented start-date imputation, flagged in the crosswalk.
    assert query("select drug_exposure_end_date = drug_exposure_start_date, verbatim_end_date "
                 "from work_omop.drug_exposure where person_id = %s", (p06,)) == [(True, None)]
    assert query("select end_date_imputed from work_omop.cw_event_crosswalk "
                 "where destination_table = 'drug_exposure' and person_id = %s", (p06,)) == [(True,)]


def test_03_publish_baseline_and_bi_reader_sees_it(disposable_database, expected):
    release = publish(STATE["run_A"])
    assert release["release_id"] == "r0001"
    assert validate_release("r0001")["ok"]
    assert query("select release_id from bi.bi_release_status", role="bi_reader") == [("r0001",)]
    _assert_matches_expected("bi", expected, "fixture-A", role="bi_reader")


@pytest.mark.parametrize(
    ("role", "relation"),
    [
        ("bi_reader", "raw.patients"), ("bi_reader", "ops.batch"), ("bi_reader", "stg.stg_synthea__patients"),
        ("bi_reader", "work_bi.bi_patient_snapshot"), ("bi_reader", "star.dim_patient"),
        ("bi_reader", "omop.person"), ("omop_reader", "raw.patients"), ("omop_reader", "int.int_patients"),
        ("omop_reader", "work_omop.person"), ("omop_reader", "bi.bi_patient_snapshot"),
    ],
)
def test_04_reader_roles_are_denied_outside_their_marts(disposable_database, role, relation):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        query(f"select 1 from {relation} limit 1", role=role)


def test_04b_reader_roles_can_read_their_marts_but_not_change_them(disposable_database):
    assert query("select count(*) from omop.person", role="omop_reader")[0][0] > 0
    assert query("select count(*) from omop.concept", role="omop_reader")[0][0] > 0
    assert query("select count(*) from bi_r0001.bi_cohort_membership", role="bi_reader")[0][0] > 0
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        query("update bi_r0001.bi_release_status set release_id = 'tampered'", role="bi_reader")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        query("select person_source_value from raw.patients", role="omop_reader")


def test_05_failed_incremental_run_keeps_release_and_rolls_back_the_failing_slice(disposable_database, expected):
    assert ingest(FIXTURE / "batch_B" / "manifest.json").outcome == "loaded"
    with env(CW_INJECT_FAILURE_MODEL="fct_observation"), pytest.raises(BuildError):
        run_pipeline(batch_id="fixture-B")

    # Consumers still see the previous validated release.
    assert query("select release_id from bi.bi_release_status", role="bi_reader") == [("r0001",)]
    _assert_matches_expected("bi", expected, "fixture-A", role="bi_reader")
    # The failing model's slice replacement rolled back as one transaction: P13 still has the old 140 value...
    p13 = _patient_key(13)
    values = query("select value_as_number from work_star.fct_observation o join work_star.dim_clinical_code c "
                   "using (clinical_code_key) where o.patient_key = %s and c.source_code = '8480-6'", (p13,))
    assert [float(v[0]) for v in values] == [140.0]
    # ...while the changed people are remembered for the retry.
    pending = {r[0] for r in query("select patient_id from ops.pending_person")}
    assert pending == {patient_uuid(n) for n in expected["after_batch"]["fixture-B"]["changed_people"]}
    assert query("select status from ops.pipeline_run order by started_at desc limit 1") == [("failed",)]


def test_06_retry_is_incremental_correct_and_keeps_keys(disposable_database, expected):
    result = run_pipeline(batch_id="fixture-B")
    assert result["mode"] == "incremental"
    assert result["quality_gate"]["status"] == "validated"
    changed = {r[0] for r in query('select patient_id from "int".int_changed_person')}
    assert changed == {patient_uuid(n) for n in expected["after_batch"]["fixture-B"]["changed_people"]}
    _assert_matches_expected("work_bi", expected, "fixture-B")
    assert query("select count(*) from ops.pending_person") == [(0,)]
    # Type 1 correction overwrote race but kept the key; the removed person has no fact rows left.
    assert _patient_key(1) == STATE["p01_key"]
    assert query("select race from work_star.dim_patient where patient_key = %s", (STATE["p01_key"],)) == [("asian",)]
    p25 = _patient_key(25)
    for table in ("fct_encounter", "fct_condition", "fct_observation"):
        assert query(f"select count(*) from work_star.{table} where patient_key = %s", (p25,)) == [(0,)]
    STATE["run_B"] = result["run_id"]


def test_07_injected_publication_failure_changes_nothing(disposable_database):
    with env(CW_INJECT_PUBLISH_FAILURE="before_commit"), pytest.raises(PublicationError, match="injected"):
        publish(STATE["run_B"])
    assert query("select release_id from ops.current_release") == [("r0001",)]
    assert query("select count(*) from pg_namespace where nspname = 'bi_r0002'") == [(0,)]
    assert query("select release_id from bi.bi_release_status", role="bi_reader") == [("r0001",)]
    assert query("select count(*) from ops.release_event where event = 'publish_failed'")[0][0] >= 1

    release = publish(STATE["run_B"])
    assert release["release_id"] == "r0002"


def test_08_replay_of_same_content_changes_nobody_and_nothing(disposable_database, expected):
    assert ingest(FIXTURE / "batch_C" / "manifest.json").outcome == "loaded"
    result = run_pipeline(batch_id="fixture-C")
    assert result["mode"] == "incremental"
    assert query('select count(*) from "int".int_changed_person') == [(0,)]
    _assert_matches_expected("work_bi", expected, "fixture-C")
    release = publish(result["run_id"])
    assert release["release_id"] == "r0003"
    for mart in ("star", "omop", "bi"):
        assert snapshot_schema(f"{mart}_r0002") == snapshot_schema(f"{mart}_r0003"), mart
    STATE["run_C"] = result["run_id"]


def test_09_incremental_state_equals_an_independent_full_rebuild(disposable_database):
    incremental = {mart: snapshot_schema(mart) for mart in ("work_star", "work_omop", "work_bi")}
    registry_before = query("select entity_type, natural_key, surrogate_id from ops.entity_key_map order by 1, 2")
    result = run_pipeline(batch_id="fixture-C", full_refresh=True)
    assert result["mode"] == "full_refresh"
    for mart, content in incremental.items():
        rebuilt = snapshot_schema(mart)
        assert rebuilt.keys() == content.keys()
        for table in content:
            assert rebuilt[table] == content[table], f"{mart}.{table} differs between incremental and full rebuild"
    registry_after = query("select entity_type, natural_key, surrogate_id from ops.entity_key_map order by 1, 2")
    assert registry_after == registry_before, "a replay/full refresh must not allocate or change keys"


def test_10_restore_previous_release_within_budget_and_back(disposable_database, expected):
    started = time.perf_counter()
    result = restore("r0001", reason="recovery drill")
    assert time.perf_counter() - started < 15 * 60
    assert result["restored_release_id"] == "r0001"
    assert query("select release_id from bi.bi_release_status", role="bi_reader") == [("r0001",)]
    _assert_matches_expected("bi", expected, "fixture-A", role="bi_reader")
    restore("r0003", reason="return to intended release")
    assert query("select release_id, previous_release_id from ops.current_release") == [("r0003", "r0001")]


def test_11_retention_dry_run_keeps_current_previous_and_pinned(disposable_database):
    plan = cleanup(dataset_id="fixture", apply=False)
    kept = {r["release_id"] for r in plan["releases_kept"]}
    assert kept == {"r0003", "r0001"}
    assert plan["releases_droppable"] == ["r0002"]
    assert set(plan["raw_batches_required"]) >= {"fixture-A", "fixture-C"}


def test_12_wrong_person_visit_link_blocks_publication(disposable_database, batch_copy):
    import csv
    import io

    from cohortwarehouse.manifest import build_manifest, write_manifest
    from scripts.build_fixture import generator_block

    directory = batch_copy("batch_A")
    rows = list(csv.reader(io.StringIO((directory / "conditions.csv").read_text(encoding="utf-8"), newline="")))
    header = rows[0]
    for row in rows[1:]:
        if row[header.index("PATIENT")] == patient_uuid(1) and row[header.index("ENCOUNTER")]:
            row[header.index("ENCOUNTER")] = "e0000002-0000-4000-8000-000000000001"  # patient 02's encounter
            break
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\n").writerows(rows)
    (directory / "conditions.csv").write_bytes(buffer.getvalue().encode("utf-8"))
    document = build_manifest(directory, dataset_id="fixture_wrong_visit", batch_id="wrong-visit-A",
                              source_revision=1, as_of_date="2026-06-30", delivered_at="2026-07-01T04:30:00Z",
                              generator=generator_block(),
                              expected_quarantine=[{"file": "encounters", "record_number": 43,
                                                    "reason": "invalid_timestamp"},
                                                   {"file": "observations", "record_number": 6,
                                                    "reason": "field_count_mismatch"}])
    write_manifest(directory, document)
    ingest(directory / "manifest.json")
    with pytest.raises(QualityGateError):
        run_pipeline(batch_id="wrong-visit-A")
    failed_run = query("select run_id, status from ops.pipeline_run where dataset_id = 'fixture_wrong_visit'")
    assert failed_run[0][1] == "failed"
    with pytest.raises(PublicationError):
        publish(failed_run[0][0])
    # The fixture dataset's published release is untouched.
    assert query("select release_id from bi.bi_release_status", role="bi_reader") == [("r0003",)]
