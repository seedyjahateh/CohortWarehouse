"""Measured benchmark runs (NFR-01/02, Section 14). Reports what was measured; never extrapolates.

Full-load runs rebuild candidates with --full-refresh and publish; stage timings come from ops.pipeline_run.
Raw-load throughput (accepted rows / loader seconds) is reported separately from end-to-end time.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import platform
import statistics
import time

from cohortwarehouse.db import connect, fetch_all_dicts, fetch_one_dict
from cohortwarehouse.errors import QualityGateError
from cohortwarehouse.ingest import ingest
from cohortwarehouse.manifest import load_manifest
from cohortwarehouse.pipeline import run_pipeline
from cohortwarehouse.publish import publish
from cohortwarehouse.settings import repo_root

log = logging.getLogger(__name__)


def _hardware() -> dict:
    info = {"platform": platform.platform(), "python": platform.python_version(), "logical_cpus": os.cpu_count()}
    with connect("admin") as conn:
        info["postgres"] = fetch_one_dict(conn, "select version()")["version"]
        info["postgres_settings"] = {r["name"]: r["setting"] for r in fetch_all_dicts(
            conn, "select name, setting from pg_settings where name in "
                  "('shared_buffers', 'work_mem', 'max_parallel_workers_per_gather', 'effective_cache_size')")}
    return info


def benchmark(*, profile: str = "demo", runs: int = 3, manifest: str | None = None) -> dict:
    if manifest is None:
        raise ValueError("pass --manifest pointing at the benchmark delivery (python -m cohortwarehouse generate)")
    loaded = load_manifest(manifest)
    load_started = time.perf_counter()
    ingest_result = ingest(manifest)
    load_seconds = time.perf_counter() - load_started
    accepted = sum(f.accepted for f in ingest_result.files.values())

    measurements = []
    for index in range(runs):
        started = time.perf_counter()
        gate_error = None
        try:
            run_pipeline(batch_id=loaded.batch_id, full_refresh=True,
                         profile="release" if profile == "release" else None, trigger="benchmark")
        except QualityGateError as exc:
            # A blocked gate is a measured outcome, not a crash: build timings are still real evidence.
            gate_error = str(exc)
        with connect("transformer") as conn:
            run = fetch_one_dict(
                conn,
                "select run_id, status, stage_timings, counts from ops.pipeline_run "
                "where target_batch_id = %s and trigger = 'benchmark' order by started_at desc limit 1",
                (loaded.batch_id,),
            )
        build_seconds = time.perf_counter() - started
        release = publish(run["run_id"]) if run["status"] == "validated" else None
        total = time.perf_counter() - started
        measurements.append({
            "run": index + 1, "run_id": run["run_id"], "gate_status": run["status"],
            "gate_blocking_failures": gate_error,
            "release_id": release["release_id"] if release else None,
            "build_and_gate_seconds": round(build_seconds, 1),
            "publish_seconds": release["seconds"] if release else None,
            "end_to_end_seconds": round(total, 1) if release else None,
            "stage_timings": run["stage_timings"],
        })
        log.info("benchmark run %d: build+gate %.1fs, gate=%s", index + 1, build_seconds, run["status"])

    with connect("admin") as conn:
        rows = fetch_all_dicts(conn, "select file_key, parsed_records, accepted_records, quarantined_records, "
                                     "load_seconds from ops.batch_file where batch_id = %s order by file_key",
                               (loaded.batch_id,))
    # Loader timings recorded at ingestion (valid even when this benchmark found the batch already loaded).
    recorded_load_seconds = float(sum(r["load_seconds"] or 0 for r in rows))
    recorded_accepted = sum(r["accepted_records"] for r in rows)
    builds = [m["build_and_gate_seconds"] for m in measurements]
    totals = [m["end_to_end_seconds"] for m in measurements if m["end_to_end_seconds"] is not None]
    report = {
        "profile": profile,
        "measured_at_utc": dt.datetime.now(dt.UTC).isoformat(),
        "hardware": _hardware(),
        "batch_id": loaded.batch_id,
        "source_rows": rows,
        "raw_load": {"outcome_this_invocation": ingest_result.outcome,
                     "invocation_seconds": round(load_seconds, 2) if ingest_result.outcome == "loaded" else None,
                     "recorded_file_load_seconds": round(recorded_load_seconds, 1),
                     "accepted_rows": recorded_accepted,
                     "accepted_rows_per_second": round(recorded_accepted / recorded_load_seconds, 1)
                     if recorded_load_seconds else None},
        "runs": measurements,
        "build_and_gate_seconds": {"min": min(builds), "median": statistics.median(builds), "max": max(builds)},
        "end_to_end_seconds": ({"min": min(totals), "median": statistics.median(totals), "max": max(totals)}
                               if len(totals) == len(measurements) else None),
        "target_seconds": 20 * 60,
        # NFR-01 includes publication: it is only assessed when every run published.
        "meets_target": (max(totals) <= 20 * 60) if totals and len(totals) == len(measurements) else None,
    }
    directory = repo_root() / "artifacts" / "benchmark"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{profile}-{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    report["report_path"] = str(path)
    return report
