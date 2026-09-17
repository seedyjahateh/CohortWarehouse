"""DAG structure contract (Section 9.3, CI step 6). Runs with the pinned Airflow runtime only."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

airflow = pytest.importorskip("airflow", reason="pinned Airflow runtime not installed (CI job `airflow`)")
pytestmark = pytest.mark.airflow

DAGS = Path(__file__).resolve().parents[2] / "dags"


@pytest.fixture(scope="module")
def dag(monkeypatch_module):
    from airflow.models.dagbag import DagBag

    bag = DagBag(dag_folder=str(DAGS), include_examples=False)
    assert not bag.import_errors, bag.import_errors
    return bag.get_dag("cohortwarehouse_daily")


@pytest.fixture(scope="module")
def monkeypatch_module():
    """Fail the parse if the DAG file opens a network connection at import time."""
    original = socket.socket.connect

    def forbidden(*args, **kwargs):
        raise AssertionError("DAG performed network I/O at import time")

    socket.socket.connect = forbidden
    try:
        yield
    finally:
        socket.socket.connect = original


def test_schedule_and_run_policy(dag):
    assert dag is not None
    assert str(dag.timetable.summary) == "15 5 * * *" or "15 5 * * *" in str(dag.timetable)
    assert dag.catchup is False
    assert dag.max_active_runs == 1
    assert dag.dagrun_timeout.total_seconds() == 40 * 60
    assert str(dag.timezone) in {"UTC", "Timezone('UTC')"} or "UTC" in str(dag.timezone)


def test_task_order(dag):
    order = [
        "resolve_manifest", "validate_and_load_raw", "check_delivery_freshness", "prepare_changed_persons",
        "dbt_build_staging_intermediate", "dbt_build_star_omop", "dbt_build_bi", "quality_and_reconciliation_gate",
        "publish_release", "generate_docs_and_release_report", "record_run_summary",
    ]
    assert set(order) == set(dag.task_ids)
    for upstream, downstream in zip(order, order[1:], strict=False):
        assert downstream in dag.get_task(upstream).downstream_task_ids or upstream == "publish_release", (
            upstream, downstream)


def test_parameters_and_retries(dag):
    assert {"batch_id", "manifest_path", "full_refresh", "validation_only"} <= set(dag.params.keys())
    assert dag.get_task("validate_and_load_raw").retries == 2
    assert dag.get_task("quality_and_reconciliation_gate").retries == 0
    writers = {t.task_id for t in dag.tasks if t.pool == "cohortwarehouse_warehouse_write"}
    assert {"validate_and_load_raw", "dbt_build_bi", "publish_release"} <= writers
