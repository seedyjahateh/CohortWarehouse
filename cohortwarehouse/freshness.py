"""Delivery freshness (NFR-05): measured on manifest delivery time, never on clinical event dates."""

from __future__ import annotations

import datetime as dt

from cohortwarehouse.db import connect, fetch_one_dict
from cohortwarehouse.settings import pipeline_config


def evaluate(latest_delivery: dt.datetime | None, *, now: dt.datetime, mode: str, warn_hours: float,
             error_hours: float) -> dict:
    if latest_delivery is None:
        return {"status": "fail", "mode": mode, "reason": "no delivery has ever been loaded"}
    age_hours = round((now - latest_delivery).total_seconds() / 3600.0, 2)
    report = {"mode": mode, "latest_delivery_utc": latest_delivery.isoformat(), "age_hours": age_hours,
              "warn_after_hours": warn_hours, "error_after_hours": error_hours}
    if mode == "frozen_demo":
        # A labelled demo: the declared one-off delivery is the schedule. Report age, never call it fresh.
        return {**report, "status": "pass", "label": "FROZEN DEMO - delivery age reported, not a freshness SLA"}
    if age_hours > error_hours:
        return {**report, "status": "fail"}
    if age_hours > warn_hours:
        return {**report, "status": "warn"}
    return {**report, "status": "pass"}


def check_freshness(dataset_id: str, *, mode: str | None = None, now: dt.datetime | None = None) -> dict:
    config = pipeline_config()["freshness"]
    mode = mode or config["mode"]
    with connect("transformer") as conn:
        row = fetch_one_dict(
            conn, "select max(delivered_at) as latest from ops.batch where dataset_id = %s", (dataset_id,)
        )
    return {
        "dataset_id": dataset_id,
        **evaluate(
            row["latest"] if row else None,
            now=now or dt.datetime.now(dt.UTC),
            mode=mode,
            warn_hours=config["warn_after_hours"],
            error_hours=config["error_after_hours"],
        ),
    }
