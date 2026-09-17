"""Loader contract and rejection fixtures (ING-02..07). Each test uses its own dataset id, so it only needs a
bootstrapped database, not a disposable one."""

from __future__ import annotations

import json
import uuid

import pytest

from cohortwarehouse.errors import ContractError, ProvenanceError
from cohortwarehouse.ingest import ingest
from cohortwarehouse.manifest import build_manifest, write_manifest
from scripts.build_fixture import generator_block
from tests.conftest import patient_uuid
from tests.integration.helpers import query

pytestmark = pytest.mark.integration

A_QUARANTINE = [
    {"file": "encounters", "record_number": 43, "reason": "invalid_timestamp"},
    {"file": "observations", "record_number": 6, "reason": "field_count_mismatch"},
]


def _dataset() -> str:
    return f"t_{uuid.uuid4().hex[:12]}"


def _manifest(directory, dataset, batch_id, revision=1, **kwargs):
    document = build_manifest(directory, dataset_id=dataset, batch_id=batch_id, source_revision=revision,
                              as_of_date="2026-06-30", delivered_at="2026-07-01T04:30:00Z",
                              generator=generator_block(), **kwargs)
    return write_manifest(directory, document)


@pytest.fixture(autouse=True)
def _bootstrapped(database):
    if not query("select to_regclass('ops.batch')")[0][0]:
        pytest.skip("warehouse is not bootstrapped (python -m cohortwarehouse bootstrap)")


def test_renamed_required_column_rejects_whole_batch(batch_copy):
    directory = batch_copy("batch_A")
    path = directory / "observations.csv"
    content = path.read_bytes().decode("utf-8")
    path.write_bytes(content.replace("DATE,PATIENT", "OBS_DATE,PATIENT", 1).encode("utf-8"))
    dataset = _dataset()
    manifest = _manifest(directory, dataset, f"{dataset}-1", expected_quarantine=A_QUARANTINE)
    with pytest.raises(ContractError, match="missing or renamed required columns"):
        ingest(manifest)
    assert query("select count(*) from ops.batch where dataset_id = %s", (dataset,)) == [(0,)]
    assert query("select count(*) from raw.patients where _dataset_id = %s", (dataset,)) == [(0,)]
    assert query("select outcome from ops.load_attempt where manifest_path = %s", (str(manifest),)) == [("rejected",)]


def test_declared_count_mismatch_rolls_back_every_file(batch_copy):
    directory = batch_copy("batch_A")
    dataset = _dataset()
    manifest = _manifest(directory, dataset, f"{dataset}-1", expected_quarantine=A_QUARANTINE)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["files"]["observations"]["records"] += 1  # observations is loaded after patients/encounters
    manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ContractError, match="declares"):
        ingest(manifest)
    for table in ("patients", "encounters", "conditions"):
        assert query(f"select count(*) from raw.{table} where _dataset_id = %s", (dataset,)) == [(0,)]


def test_missing_provenance_is_rejected_before_loading(batch_copy):
    directory = batch_copy("batch_A")
    dataset = _dataset()
    manifest = _manifest(directory, dataset, f"{dataset}-1")
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["synthetic"] = False
    manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ProvenanceError):
        ingest(manifest)
    assert query("select count(*) from ops.batch where dataset_id = %s", (dataset,)) == [(0,)]


def test_revision_order_batch_reuse_and_scope_rules(batch_copy):
    dataset = _dataset()
    full = batch_copy("batch_A")
    assert ingest(_manifest(full, dataset, f"{dataset}-full", revision=2,
                            expected_quarantine=A_QUARANTINE)).outcome == "loaded"

    # A later delivery may not carry an older revision.
    older = batch_copy("batch_B")
    manifest = _manifest(older, dataset, f"{dataset}-older", revision=1, replacement_mode="scoped",
                         patient_scope=[patient_uuid(n) for n in (1, 9, 13, 24, 25, 26)])
    with pytest.raises(ContractError, match="monotonic"):
        ingest(manifest)

    # Reusing a batch id for different content is refused.
    reused = _manifest(older, dataset, f"{dataset}-full", revision=3, replacement_mode="scoped",
                       patient_scope=[patient_uuid(n) for n in (1, 9, 13, 24, 25, 26)])
    with pytest.raises(ContractError, match="never be reused"):
        ingest(reused)

    # Rows for people outside the declared scope are quarantined, never silently applied.
    narrow = _manifest(older, dataset, f"{dataset}-scoped", revision=3, replacement_mode="scoped",
                       patient_scope=[patient_uuid(n) for n in (1, 9, 13, 24, 25)])
    result = ingest(narrow)
    out_of_scope = query("select file_key, count(*) from ops.quarantine where batch_id = %s "
                         "and reason = 'patient_out_of_scope' group by file_key order by 1", (f"{dataset}-scoped",))
    assert dict(out_of_scope) == {"conditions": 1, "encounters": 1, "medications": 1, "observations": 1,
                                  "patients": 1}
    assert result.files["patients"].accepted == 4


def test_duplicate_natural_keys_are_quarantined_together(batch_copy):
    directory = batch_copy("batch_A")
    path = directory / "organizations.csv"
    lines = path.read_bytes().decode("utf-8").splitlines(keepends=True)
    path.write_bytes("".join([*lines, lines[1]]).encode("utf-8"))
    dataset = _dataset()
    manifest = _manifest(directory, dataset, f"{dataset}-1", expected_quarantine=A_QUARANTINE)
    result = ingest(manifest)
    assert result.files["organizations"].quarantined == 2
    assert result.files["organizations"].accepted == 1
    reasons = query("select distinct reason from ops.quarantine where batch_id = %s and file_key = 'organizations'",
                    (f"{dataset}-1",))
    assert reasons == [("duplicate_natural_key",)]
