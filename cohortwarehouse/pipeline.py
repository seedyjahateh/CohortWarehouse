"""Candidate build orchestration shared by the CLI and the Airflow DAG (Section 9.2-9.3).

Every step takes only a run_id (plus stage name); all state lives in ops.pipeline_run, so Airflow
retries and CLI reruns re-enter the same code with the same pinned input revision.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from cohortwarehouse.db import connect, fetch_all_dicts, fetch_one_dict, jsonb, warehouse_write_lock
from cohortwarehouse.dbt_runner import STAGES, run_dbt
from cohortwarehouse.errors import CohortWarehouseError, ConfigurationError, ContractError
from cohortwarehouse.settings import repo_root, validation_profile

log = logging.getLogger(__name__)

RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,120}$")
FINGERPRINT_INPUTS = ("dbt/models", "dbt/macros", "dbt/seeds", "dbt/tests", "dbt/dbt_project.yml",
                      "config/source_contract.yml")


def git_sha() -> str:
    """Short commit of the running code; '-dirty' when tracked files differ. 'unknown' outside a checkout."""
    git = shutil.which("git")
    if git is None:
        return os.environ.get("CW_GIT_SHA", "unknown")
    try:
        sha = subprocess.run([git, "rev-parse", "HEAD"], cwd=repo_root(), capture_output=True, text=True,
                             check=True, timeout=10).stdout.strip()
        dirty = subprocess.run([git, "status", "--porcelain", "--untracked-files=no"], cwd=repo_root(),
                               capture_output=True, text=True, check=True, timeout=10).stdout.strip()
        return f"{sha[:12]}-dirty" if dirty else sha[:12]
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def build_fingerprint(vocabulary_version: str | None) -> str:
    """Hash of transformation logic, mapping seeds, source contract and vocabulary version.

    A change triggers a full affected-model rebuild even when source files are identical (Section 9.2.4).
    Line endings are normalised so Windows and Linux checkouts agree.
    """
    root = repo_root()
    digest = hashlib.sha256()
    for relative in FINGERPRINT_INPUTS:
        path = root / relative
        if not path.exists():
            digest.update(f"missing:{relative}".encode())
            continue
        files = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
        for file in files:
            digest.update(file.relative_to(root).as_posix().encode())
            digest.update(file.read_bytes().replace(b"\r\n", b"\n"))
    digest.update(f"vocabulary={vocabulary_version}".encode())
    return digest.hexdigest()


def _new_run_id(batch_id: str) -> str:
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{batch_id}.{stamp}"


def validate_run_id(run_id: str) -> str:
    if not RUN_ID_RE.match(run_id):
        raise ConfigurationError(f"invalid run id {run_id!r}")
    return run_id


def start_run(
    batch_id: str,
    *,
    full_refresh: bool = False,
    validation_only: bool = False,
    trigger: str = "cli",
    run_id: str | None = None,
) -> dict:
    """Pin the input revision and decide incremental vs full refresh. Idempotent for a given run_id."""
    run_id = validate_run_id(run_id or _new_run_id(batch_id))
    with connect("transformer") as conn:
        existing = fetch_one_dict(conn, "select * from ops.pipeline_run where run_id = %s", (run_id,))
        if existing:
            return existing
        batch = fetch_one_dict(conn, "select * from ops.batch where batch_id = %s", (batch_id,))
        if not batch:
            raise ContractError(f"batch {batch_id!r} has not been ingested")
        vocab = fetch_one_dict(conn, "select vocabulary_version from ops.vocabulary_release where is_current")
        if not vocab:
            raise ConfigurationError("no current vocabulary loaded; run load-vocabulary first")
        fingerprint = build_fingerprint(vocab["vocabulary_version"])
        reference = fetch_one_dict(
            conn,
            """
            select encode(sha256(convert_to(coalesce(string_agg(id, ',' order by id), ''), 'UTF8')), 'hex') as fp
            from raw.organizations where _batch_id = %s
            """,
            (batch_id,),
        )["fp"]

        reasons: list[str] = []
        if full_refresh:
            reasons.append("requested")
        last = fetch_one_dict(conn, "select * from ops.build_state where dataset_id = %s", (batch["dataset_id"],))
        owner = fetch_one_dict(conn, "select dataset_id from ops.candidate_owner")
        if not last:
            reasons.append("no_previous_build")
        else:
            if owner and owner["dataset_id"] != batch["dataset_id"]:
                reasons.append("candidate_schemas_hold_another_dataset")
            if last["build_fingerprint"] != fingerprint:
                reasons.append("transformation_mapping_or_vocabulary_changed")
            if last["as_of_date"] != batch["as_of_date"]:
                reasons.append("as_of_date_changed")
            if last["reference_fingerprint"] != reference:
                reasons.append("organization_id_set_changed")
            if batch["source_revision"] < last["source_revision"]:
                reasons.append("target_revision_precedes_built_revision")
        if validation_only:
            reasons.append("validation_only")
        mode = "validation_only" if validation_only else ("full_refresh" if reasons else "incremental")

        with conn.cursor() as cur:
            cur.execute(
                """
                insert into ops.pipeline_run (run_id, dataset_id, target_batch_id, target_revision, as_of_date,
                    mode, full_refresh_reason, build_fingerprint, reference_fingerprint, vocabulary_version, git_sha,
                    trigger, status)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'started')
                """,
                (run_id, batch["dataset_id"], batch_id, batch["source_revision"], batch["as_of_date"], mode,
                 ",".join(reasons) or None, fingerprint, reference, vocab["vocabulary_version"], git_sha(),
                 trigger),
            )
        conn.commit()
        log.info("run %s: batch %s revision %s mode=%s reasons=%s", run_id, batch_id, batch["source_revision"],
                 mode, reasons or "-")
        return fetch_one_dict(conn, "select * from ops.pipeline_run where run_id = %s", (run_id,))


def _run(run_id: str) -> dict:
    with connect("transformer") as conn:
        run = fetch_one_dict(conn, "select * from ops.pipeline_run where run_id = %s", (validate_run_id(run_id),))
    if not run:
        raise ConfigurationError(f"unknown run {run_id}")
    return run


def _record_timing(run_id: str, key: str, seconds: float, counts: dict | None = None) -> None:
    with connect("transformer") as conn, conn.cursor() as cur:
        cur.execute(
            """
            update ops.pipeline_run
               set stage_timings = stage_timings || jsonb_build_object(%s::text, %s::numeric),
                   counts = counts || %s
             where run_id = %s
            """,
            (key, round(seconds, 3), jsonb(counts or {}), run_id),
        )
        conn.commit()


def is_full_refresh(run: dict) -> bool:
    # A validation-only build of a historical revision can never be applied incrementally.
    return run["mode"] in {"full_refresh", "validation_only"}


def build_stage(run_id: str, stage: str) -> dict:
    if stage not in STAGES:
        raise ConfigurationError(f"unknown stage {stage}")
    run = _run(run_id)
    if run["status"] not in {"started", "built", "failed"}:
        raise ConfigurationError(f"run {run_id} is {run['status']}; build stages cannot be rerun")
    with connect("transformer") as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into ops.candidate_owner (singleton, dataset_id, run_id) values (true, %s, %s)
            on conflict (singleton) do update
               set dataset_id = excluded.dataset_id, run_id = excluded.run_id, updated_at = now()
            """,
            (run["dataset_id"], run_id),
        )
        conn.commit()
    result = run_dbt("build", run_id=run_id, label=stage, select=STAGES[stage], full_refresh=is_full_refresh(run),
                     git_sha=run["git_sha"] or "unknown")
    counts: dict = {f"dbt_{stage}": result.counts}
    if stage == "staging_intermediate":
        with connect("transformer") as conn:
            changed = fetch_all_dicts(
                conn, 'select change_type, count(*) as n from "int".int_changed_person group by change_type'
            )
        counts["changed_people"] = {r["change_type"]: r["n"] for r in changed}
    _record_timing(run_id, stage, result.seconds, counts)
    return {"run_id": run_id, "stage": stage, "seconds": result.seconds, "dbt": result.counts, **counts}


def record_built_state(run_id: str) -> dict:
    """After every model built: remember what the candidate schemas now contain and clear pending people."""
    run = _run(run_id)
    with connect("transformer") as conn, conn.cursor() as cur:
        cur.execute("select pg_advisory_xact_lock(hashtextextended('cohortwarehouse:built-state', 0))")
        if is_full_refresh(run):
            cur.execute("delete from ops.person_state_built where dataset_id = %s", (run["dataset_id"],))
        else:
            cur.execute(
                """
                delete from ops.person_state_built b
                 using "int".int_changed_person c
                 where b.dataset_id = c.dataset_id and b.patient_id = c.patient_id
                """
            )
        cur.execute(
            """
            insert into ops.person_state_built (dataset_id, patient_id, person_fingerprint, source_revision, run_id)
            select f.dataset_id, f.patient_id, f.person_fingerprint, %s, %s
            from "int".int_person_fingerprint f
            inner join "int".int_changed_person c
                on c.dataset_id = f.dataset_id and c.patient_id = f.patient_id
            """,
            (run["target_revision"], run_id),
        )
        inserted = cur.rowcount
        cur.execute("delete from ops.pending_person where dataset_id = %s", (run["dataset_id"],))
        cur.execute(
            """
            insert into ops.build_state (dataset_id, run_id, source_revision, build_fingerprint, vocabulary_version,
                reference_fingerprint, as_of_date, built_at)
            values (%s, %s, %s, %s, %s, %s, %s, now())
            on conflict (dataset_id) do update
               set run_id = excluded.run_id, source_revision = excluded.source_revision,
                   build_fingerprint = excluded.build_fingerprint,
                   vocabulary_version = excluded.vocabulary_version,
                   reference_fingerprint = excluded.reference_fingerprint,
                   as_of_date = excluded.as_of_date, built_at = excluded.built_at
            """,
            (run["dataset_id"], run_id, run["target_revision"], run["build_fingerprint"], run["vocabulary_version"],
             run["reference_fingerprint"], run["as_of_date"]),
        )
        cur.execute("update ops.pipeline_run set status = 'built', built_at = now() where run_id = %s", (run_id,))
        conn.commit()
    return {"run_id": run_id, "person_states_written": inserted}


def mark_failed(run_id: str, exc: BaseException) -> None:
    try:
        with connect("transformer") as conn, conn.cursor() as cur:
            cur.execute(
                """
                update ops.pipeline_run
                   set status = 'failed', finished_at = now(), error_class = %s, error_message = %s
                 where run_id = %s and status <> 'published'
                """,
                (type(exc).__name__, str(exc)[:4000], run_id),
            )
            cur.execute(
                """
                insert into ops.alert_event (dataset_id, run_id, source, severity, message, detail)
                select dataset_id, run_id, 'pipeline', 'error', %s, %s from ops.pipeline_run where run_id = %s
                """,
                (f"run failed: {type(exc).__name__}", jsonb({"error": str(exc)[:2000]}), run_id),
            )
            conn.commit()
    except CohortWarehouseError:
        log.exception("could not record failure for run %s", run_id)


def run_pipeline(
    *,
    batch_id: str,
    full_refresh: bool = False,
    validation_only: bool = False,
    profile: str | None = None,
    trigger: str = "cli",
) -> dict:
    from cohortwarehouse.quality import quality_gate

    profile_name, _ = validation_profile(profile)
    started = time.perf_counter()
    with connect("transformer") as conn:
        batch = fetch_one_dict(conn, "select dataset_id from ops.batch where batch_id = %s", (batch_id,))
    if not batch:
        raise ContractError(f"batch {batch_id!r} has not been ingested")

    with warehouse_write_lock("transformer", batch["dataset_id"]):
        run = start_run(batch_id, full_refresh=full_refresh, validation_only=validation_only, trigger=trigger)
        run_id = run["run_id"]
        try:
            stages = {stage: build_stage(run_id, stage) for stage in STAGES}
            built = record_built_state(run_id)
            gate = quality_gate(run_id, profile=profile_name)
        except BaseException as exc:
            mark_failed(run_id, exc)
            raise
    total = round(time.perf_counter() - started, 3)
    _record_timing(run_id, "total_run", total)
    return {
        "run_id": run_id,
        "mode": run["mode"],
        "full_refresh_reason": run["full_refresh_reason"],
        "stages": stages,
        "built_state": built,
        "quality_gate": gate,
        "seconds": total,
        "next_step": f"python -m cohortwarehouse publish --validated-run {run_id}"
        if gate["status"] == "validated" and run["mode"] != "validation_only" else None,
    }


def artifacts_dir(run_id: str) -> Path:
    return repo_root() / "dbt" / "target" / "runs" / run_id
