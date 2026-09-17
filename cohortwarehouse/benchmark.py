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
        result = run_pipeline(batch_id=loaded.batch_id, full_refresh=True, profile="release" if profile == "release"
                              else None, trigger="benchmark")
        release = publish(result["run_id"])
        total = time.perf_counter() - started
        with connect("transformer") as conn:
            run = fetch_one_dict(conn, "select stage_timings, counts from ops.pipeline_run where run_id = %s",
                                 (result["run_id"],))
        measurements.append({"run": index + 1, "run_id": result["run_id"], "release_id": release["release_id"],
                             "end_to_end_seconds": round(total, 1), "publish_seconds": release["seconds"],
                             "stage_timings": run["stage_timings"]})
        log.info("benchmark run %d: %.1fs", index + 1, total)

    with connect("admin") as conn:
        rows = fetch_all_dicts(conn, "select file_key, parsed_records, accepted_records, quarantined_records "
                                     "from ops.batch_file where batch_id = %s order by file_key", (loaded.batch_id,))
    totals = [m["end_to_end_seconds"] for m in measurements]
    report = {
        "profile": profile,
        "measured_at_utc": dt.datetime.now(dt.UTC).isoformat(),
        "hardware": _hardware(),
        "batch_id": loaded.batch_id,
        "source_rows": rows,
        "raw_load": {"outcome": ingest_result.outcome, "seconds": round(load_seconds, 2),
                     "accepted_rows_per_second": round(accepted / load_seconds, 1)
                     if ingest_result.outcome == "loaded" and load_seconds else None},
        "runs": measurements,
        "end_to_end_seconds": {"min": min(totals), "median": statistics.median(totals), "max": max(totals)},
        "target_seconds": 20 * 60,
        "meets_target": max(totals) <= 20 * 60,
    }
    directory = repo_root() / "artifacts" / "benchmark"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{profile}-{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    report["report_path"] = str(path)
    return report
