"""cohortwarehouse_daily: scheduled warehouse delivery (PRD Section 9.3).

Every task delegates to the same functions the CLI uses (cohortwarehouse.*); transformations stay in dbt.
Only batch ids, run ids, paths, counts and statuses travel through XCom. No database or file I/O happens at
import time, so the DAG parses quickly and safely.
"""

from __future__ import annotations

import datetime as dt
import os
import re

from airflow.sdk import Param, dag, get_current_context, task

try:  # Airflow 3 task SDK
    from airflow.sdk.exceptions import AirflowFailException
except ImportError:  # pragma: no cover - older layout
    from airflow.exceptions import AirflowFailException

DATASET_ID = os.environ.get("CW_DATASET_ID", "synthea_demo")
WRITE_POOL = "cohortwarehouse_warehouse_write"
TRANSIENT_RETRY = {"retries": 2, "retry_delay": dt.timedelta(minutes=5)}


def _stage_environment() -> None:
    """Expose Airflow Connection credentials to the pipeline as the CW_* variables it reads (never logged)."""
    from airflow.sdk import Connection

    for stage in ("loader", "transformer", "publisher"):
        try:
            conn = Connection.get(f"cw_{stage}")
        except Exception as exc:  # noqa: BLE001 - fall back to plain environment configuration
            print(f"Airflow connection cw_{stage} unavailable ({type(exc).__name__}); using CW_* environment")
            continue
        os.environ[f"CW_{stage.upper()}_USER"] = conn.login or ""
        os.environ[f"CW_{stage.upper()}_PASSWORD"] = conn.password or ""
        if conn.host:
            os.environ["CW_PG_HOST"] = conn.host
        if conn.port:
            os.environ["CW_PG_PORT"] = str(conn.port)
        if conn.schema:
            os.environ["CW_PG_DATABASE"] = conn.schema


def _non_retryable(exc: Exception) -> Exception:
    """Contract/quality/publication failures must not be blindly retried (Section 9.3)."""
    from cohortwarehouse.errors import CohortWarehouseError

    if isinstance(exc, CohortWarehouseError) and not exc.retryable:
        return AirflowFailException(f"{type(exc).__name__}: {exc}")
    return exc


def _on_failure(context) -> None:
    """Write an operational alert event; e-mail/Slack notification is P1."""
    try:
        _stage_environment()
        from cohortwarehouse.db import connect, jsonb

        ti = context.get("task_instance")
        run_id = ti.xcom_pull(task_ids="prepare_changed_persons") if ti else None
        with connect("transformer") as conn, conn.cursor() as cur:
            cur.execute(
                "insert into ops.alert_event (dataset_id, run_id, source, severity, message, detail) "
                "values (%s, %s, 'airflow', 'error', %s, %s)",
                (DATASET_ID, run_id, f"task {ti.task_id if ti else '?'} failed",
                 jsonb({"dag_run": str(context.get("run_id")), "exception": str(context.get("exception"))[:2000]})),
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - the callback must never mask the original failure
        print(f"could not record failure alert: {type(exc).__name__}")


@dag(
    dag_id="cohortwarehouse_daily",
    schedule="15 5 * * *",
    start_date=dt.datetime(2026, 9, 1, tzinfo=dt.UTC),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=dt.timedelta(minutes=40),
    default_args={"owner": "analytics-engineering", "on_failure_callback": _on_failure,
                  "execution_timeout": dt.timedelta(minutes=20)},
    params={
        "batch_id": Param(None, type=["null", "string"], description="Rebuild an already-ingested batch (manual)."),
        "manifest_path": Param(None, type=["null", "string"], description="Explicit manifest (manual backfill)."),
        "full_refresh": Param(False, type="boolean"),
        "validation_only": Param(False, type="boolean",
                                 description="Historical build for inspection; never published."),
    },
    tags=["cohortwarehouse", "synthetic-data"],
    doc_md=__doc__,
)
def cohortwarehouse_daily():
    @task(**TRANSIENT_RETRY)
    def resolve_manifest() -> dict:
        """Pin the expected delivery for this interval; the same manifest is used by every retry."""
        context = get_current_context()
        params = context["params"]
        if params.get("batch_id"):
            return {"batch_id": params["batch_id"], "manifest_path": None}
        if params.get("manifest_path"):
            return {"batch_id": None, "manifest_path": params["manifest_path"]}
        interval_end = context["data_interval_end"] or context["logical_date"]
        root = os.environ.get("CW_DELIVERY_ROOT", "/opt/cohortwarehouse/data/deliveries")
        path = os.path.join(root, DATASET_ID, interval_end.strftime("%Y-%m-%d"), "manifest.json")
        if not os.path.isfile(path):
            raise AirflowFailException(f"expected delivery manifest is missing: {path}")
        return {"batch_id": None, "manifest_path": path}

    @task(pool=WRITE_POOL, **TRANSIENT_RETRY)
    def validate_and_load_raw(delivery: dict) -> str:
        _stage_environment()
        from cohortwarehouse.ingest import ingest

        if delivery["batch_id"]:
            return delivery["batch_id"]
        try:
            result = ingest(delivery["manifest_path"])
        except Exception as exc:
            raise _non_retryable(exc) from exc
        return result.batch_id

    @task(**TRANSIENT_RETRY)
    def check_delivery_freshness(batch_id: str) -> str:
        _stage_environment()
        from cohortwarehouse.freshness import check_freshness

        report = check_freshness(DATASET_ID)
        print({k: v for k, v in report.items() if k != "dataset_id"})
        if report["status"] == "fail":
            raise AirflowFailException(f"delivery freshness failed: {report}")
        return batch_id

    @task(pool=WRITE_POOL, **TRANSIENT_RETRY)
    def prepare_changed_persons(batch_id: str) -> str:
        """Pin the input revision and decide incremental vs full refresh (changed people are computed in dbt)."""
        _stage_environment()
        from cohortwarehouse.pipeline import start_run

        context = get_current_context()
        params = context["params"]
        safe_dag_run = re.sub(r"[^A-Za-z0-9_.:-]", "_", str(context["run_id"]))[:60]
        try:
            run = start_run(batch_id, full_refresh=bool(params.get("full_refresh")),
                            validation_only=bool(params.get("validation_only")), trigger="airflow",
                            run_id=f"{batch_id}.af.{safe_dag_run}")
        except Exception as exc:
            raise _non_retryable(exc) from exc
        return run["run_id"]

    def _stage_task(stage: str):
        @task(task_id=f"dbt_build_{stage}", pool=WRITE_POOL, **TRANSIENT_RETRY)
        def _build(run_id: str) -> str:
            _stage_environment()
            from cohortwarehouse.pipeline import build_stage

            try:
                summary = build_stage(run_id, stage)
            except Exception as exc:
                raise _non_retryable(exc) from exc
            print({k: v for k, v in summary.items() if k != "run_id"})
            return run_id

        return _build

    @task(pool=WRITE_POOL)
    def quality_and_reconciliation_gate(run_id: str) -> str:
        _stage_environment()
        from cohortwarehouse.pipeline import record_built_state
        from cohortwarehouse.quality import quality_gate

        try:
            record_built_state(run_id)
            quality_gate(run_id)
        except Exception as exc:
            raise _non_retryable(exc) from exc
        return run_id

    @task(pool=WRITE_POOL, **TRANSIENT_RETRY)
    def publish_release(run_id: str) -> str | None:
        _stage_environment()
        from cohortwarehouse.publish import publish

        if get_current_context()["params"].get("validation_only"):
            print("validation-only run: publication skipped by design")
            return None
        try:
            return publish(run_id)["release_id"]
        except Exception as exc:
            raise _non_retryable(exc) from exc

    @task(retries=2, retry_delay=dt.timedelta(minutes=2))
    def generate_docs_and_release_report(release_id: str | None, run_id: str) -> str | None:
        """A failure here is 'documentation incomplete'; the published data does not roll back."""
        _stage_environment()
        from cohortwarehouse.release_report import write_release_report

        return write_release_report(run_id, release_id)

    @task(trigger_rule="all_done")
    def record_run_summary(run_id: str) -> dict:
        _stage_environment()
        from cohortwarehouse.db import connect, fetch_one_dict

        with connect("transformer") as conn:
            run = fetch_one_dict(conn, "select run_id, status, mode, stage_timings, counts from ops.pipeline_run "
                                       "where run_id = %s", (run_id,))
        print(run)
        return {"run_id": run_id, "status": run["status"] if run else "unknown"}

    delivery = resolve_manifest()
    batch_id = check_delivery_freshness(validate_and_load_raw(delivery))
    run_id = prepare_changed_persons(batch_id)
    built = _stage_task("bi")(_stage_task("star_omop")(_stage_task("staging_intermediate")(run_id)))
    gated = quality_and_reconciliation_gate(built)
    release = publish_release(gated)
    docs = generate_docs_and_release_report(release, gated)
    summary = record_run_summary(run_id)
    docs >> summary


cohortwarehouse_daily()
