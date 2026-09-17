"""Quality and reconciliation gate (Section 11). Publication refuses any run this gate did not validate.

Every check is recorded in ops.quality_result. A skipped blocking check is a failure, not a pass.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field

from cohortwarehouse.db import connect, fetch_all_dicts, fetch_one_dict, jsonb
from cohortwarehouse.dbt_runner import run_dbt
from cohortwarehouse.errors import QualityGateError
from cohortwarehouse.freshness import check_freshness
from cohortwarehouse.settings import approved_generators, pipeline_config, validation_profile

log = logging.getLogger(__name__)

# Minimum-necessary denylist for anything a BI user can import (Section 10).
BI_COLUMN_DENYLIST = re.compile(
    r"(^|_)(first_name|last_name|middle_name|maiden_name|given_name|family_name|full_name|name|prefix|suffix|"
    r"ssn|passport|drivers|license|address|street|zip|zipcode|postal_code|lat|lon|latitude|longitude|"
    r"birth_date|birthdate|dob|patient_id|phone|email)($|_)"
)
BI_COLUMN_ALLOW = {"cohort_label", "definition_label", "month_label", "reporting_label", "organization_name"}


@dataclass
class Check:
    check_id: str
    category: str
    status: str  # pass | fail | warn | skip
    severity: str = "blocking"
    observed: float | None = None
    threshold: str | None = None
    detail: dict = field(default_factory=dict)


def _dbt_test_checks(run: dict) -> list[Check]:
    result = run_dbt("test", run_id=run["run_id"], label="quality_gate_tests", git_sha=run["git_sha"] or "unknown",
                     raise_on_failure=False)
    checks = []
    for r in result.tests():
        status = {"pass": "pass", "fail": "fail", "error": "fail", "warn": "warn", "skipped": "skip"}.get(
            r["status"], "fail")
        name = r["unique_id"].split(".", 2)[-1]
        checks.append(Check(
            check_id=f"dbt:{name}"[:200],
            category=_category(name),
            status=status,
            severity="warning" if r["status"] == "warn" else "blocking",
            observed=r.get("failures"),
            detail={"message": (r.get("message") or "")[:1000]},
        ))
    if not checks:
        checks.append(Check("dbt:tests_executed", "tests", "fail",
                            detail={"message": "dbt test produced no results", "returncode": result.returncode}))
    return checks


def _category(test_name: str) -> str:
    rules = [
        ("reconcil|conservation|accounting|slice", "conservation"),
        ("cohort", "cohort_correctness"),
        ("unique|not_null|exactly_one", "keys"),
        ("relationships|visit_link|wrong_person", "relationships"),
        ("concept|mapping|vocab", "terminology"),
        ("date|period|death|end_not_before", "temporal"),
        ("denylist|identifier", "governance"),
        ("accepted_values", "required_values"),
    ]
    for pattern, category in rules:
        if re.search(pattern, test_name):
            return category
    return "structure"


def _python_checks(conn, run: dict, profile: dict) -> list[Check]:
    checks: list[Check] = []
    dataset, revision = run["dataset_id"], run["target_revision"]

    batches = fetch_all_dicts(
        conn,
        "select batch_id, manifest, generator_name, generator_version, synthetic from ops.batch "
        "where dataset_id = %s and source_revision <= %s order by source_revision",
        (dataset, revision),
    )

    # Provenance, re-checked against the current approved list (ING-07).
    approved = {(g["name"], v) for g in approved_generators() for v in g["versions"]}
    bad = [b["batch_id"] for b in batches
           if not b["synthetic"] or (b["generator_name"], b["generator_version"]) not in approved]
    checks.append(Check("source:synthetic_provenance", "source_contract", "fail" if bad else "pass",
                        observed=len(bad), threshold="0", detail={"batches": bad}))

    # ING-06 reconciliation per file.
    rec = fetch_all_dicts(
        conn,
        """
        select f.batch_id, f.file_key, f.declared_records, f.parsed_records, f.accepted_records,
               f.quarantined_records,
               (select count(*) from ops.quarantine q where q.batch_id = f.batch_id and q.file_key = f.file_key)
                   as quarantine_rows
        from ops.batch_file f join ops.batch b using (batch_id)
        where b.dataset_id = %s and b.source_revision <= %s
        """,
        (dataset, revision),
    )
    unreconciled = [r for r in rec if r["parsed_records"] != r["accepted_records"] + r["quarantined_records"]
                    or r["quarantined_records"] != r["quarantine_rows"]
                    or r["parsed_records"] != r["declared_records"]]
    checks.append(Check("source:file_reconciliation", "source_contract", "fail" if unreconciled else "pass",
                        observed=len(unreconciled), threshold="0",
                        detail={"files_checked": len(rec), "unreconciled": unreconciled[:20]}))

    # Quarantine must match exactly what each manifest declared (zero for clean deliveries).
    mismatches = {}
    for b in batches:
        expected = Counter((q["file"], q["record_number"], q["reason"])
                           for q in b["manifest"].get("expected_quarantine", []))
        actual_rows = fetch_all_dicts(
            conn, "select file_key, record_number, reason from ops.quarantine where batch_id = %s", (b["batch_id"],)
        )
        actual = Counter((r["file_key"], r["record_number"], r["reason"]) for r in actual_rows)
        if expected != actual:
            mismatches[b["batch_id"]] = {
                "unexpected": [list(k) for k in (actual - expected)],
                "missing": [list(k) for k in (expected - actual)],
            }
    checks.append(Check("source:expected_quarantine", "source_contract", "fail" if mismatches else "pass",
                        observed=len(mismatches), threshold="0", detail=mismatches))

    # Vocabulary boundary: fictional test vocabulary can never satisfy the release profile.
    vocab = fetch_one_dict(conn, "select vocabulary_version, is_test_only from ops.vocabulary_release where is_current")
    vocab_ok = vocab is not None and (profile["allow_test_vocabulary"] or not vocab["is_test_only"])
    checks.append(Check("terminology:vocabulary_profile", "terminology", "pass" if vocab_ok else "fail",
                        detail={"vocabulary": vocab, "profile": profile["label"]}))
    if vocab and vocab["vocabulary_version"] != run["vocabulary_version"]:
        checks.append(Check("terminology:vocabulary_unchanged_since_build", "terminology", "fail",
                            detail={"built_with": run["vocabulary_version"], "current": vocab["vocabulary_version"]}))

    # MAP-06 coverage thresholds.
    coverage_cfg = pipeline_config()["coverage"]
    for row in fetch_all_dicts(conn, "select * from work_bi.bi_mapping_coverage"):
        category = row["category"]
        pct = float(row["event_weighted_coverage_pct"] or 0)
        if category == "cohort code sets":
            required = coverage_cfg["cohort_codes_min_pct"]
        elif category in coverage_cfg["categories"]:
            required = coverage_cfg["category_event_weighted_min_pct"]
        else:
            continue
        checks.append(Check(f"coverage:{category.replace(' ', '_')}", "coverage",
                            "pass" if pct >= required else "fail", observed=pct, threshold=f">= {required}",
                            detail={k: row[k] for k in row if k != "category"}))

    # Governance: column denylist on everything BI can import.
    columns = fetch_all_dicts(
        conn,
        "select table_name, column_name from information_schema.columns where table_schema = 'work_bi'",
    )
    denied = [f"{c['table_name']}.{c['column_name']}" for c in columns
              if c["column_name"] not in BI_COLUMN_ALLOW and BI_COLUMN_DENYLIST.search(c["column_name"])]
    checks.append(Check("governance:bi_column_denylist", "governance", "fail" if denied else "pass",
                        observed=len(denied), threshold="0", detail={"denied_columns": denied,
                                                                      "columns_checked": len(columns)}))
    leaked = fetch_one_dict(
        conn,
        """
        select count(*) as n from work_omop.person p
        join "int".int_patients i on p.person_source_value = i.patient_id
        """,
    )["n"]
    checks.append(Check("governance:omop_person_source_value_pseudonymous", "governance",
                        "fail" if leaked else "pass", observed=leaked, threshold="0"))

    # Candidate integrity: nothing rebuilt the candidate schemas after this run.
    state = fetch_one_dict(conn, "select run_id from ops.build_state where dataset_id = %s", (dataset,))
    same = state is not None and state["run_id"] == run["run_id"]
    checks.append(Check("release:candidate_is_this_run", "release", "pass" if same else "fail",
                        detail={"build_state_run": state["run_id"] if state else None}))
    return checks


def quality_gate(run_id: str, *, profile: str | None = None) -> dict:
    profile_name, profile_cfg = validation_profile(profile)
    with connect("transformer") as conn:
        run = fetch_one_dict(conn, "select * from ops.pipeline_run where run_id = %s", (run_id,))
    if run is None:
        raise QualityGateError(f"unknown run {run_id}")
    if run["status"] not in {"built", "failed", "validated"}:
        raise QualityGateError(f"run {run_id} is {run['status']}; the gate runs after a complete build")

    checks = _dbt_test_checks(run)
    freshness = check_freshness(run["dataset_id"])
    checks.append(Check("freshness:delivery", "freshness",
                        {"pass": "pass", "warn": "warn", "fail": "fail"}[freshness["status"]],
                        severity="warning" if freshness["status"] == "warn" else "blocking",
                        observed=freshness.get("age_hours"), detail=freshness))
    with connect("transformer") as conn:
        checks += _python_checks(conn, run, profile_cfg)
        with conn.cursor() as cur:
            cur.execute("delete from ops.quality_result where run_id = %s", (run_id,))
            for c in checks:
                cur.execute(
                    """
                    insert into ops.quality_result (run_id, check_id, category, severity, status, observed,
                        threshold, detail)
                    values (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (run_id, c.check_id, c.category, c.severity, c.status, c.observed, c.threshold,
                     jsonb(c.detail)),
                )
            blocking_failures = [c for c in checks if c.severity == "blocking" and c.status in {"fail", "skip"}]
            status = "failed" if blocking_failures else "validated"
            cur.execute(
                """
                update ops.pipeline_run
                   set status = %s, validated_at = case when %s = 'validated' then now() end,
                       error_class = case when %s = 'failed' then 'QualityGateError' end,
                       error_message = %s,
                       counts = counts || jsonb_build_object('quality', %s::jsonb, 'validation_profile', %s::text)
                 where run_id = %s
                """,
                (status, status, status,
                 None if not blocking_failures else "; ".join(c.check_id for c in blocking_failures)[:4000],
                 jsonb(dict(Counter(c.status for c in checks))), profile_name, run_id),
            )
        conn.commit()

    summary = {
        "status": status,
        "profile": profile_name,
        "checks": dict(Counter(c.status for c in checks)),
        "blocking_failures": [{"check": c.check_id, "observed": c.observed, "detail": c.detail}
                              for c in blocking_failures][:20],
    }
    log.info("quality gate for %s: %s %s", run_id, status, summary["checks"])
    if blocking_failures:
        raise QualityGateError(
            f"quality gate failed for run {run_id}: "
            + ", ".join(c.check_id for c in blocking_failures[:10])
        )
    return summary
