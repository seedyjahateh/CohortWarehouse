"""Release evidence (Section 12.2): dbt docs plus a machine-readable release manifest.

Documentation failures after publication are recorded as `docs_incomplete`; they never imply the release
rolled back.
"""

from __future__ import annotations

import json
import logging
import platform

from cohortwarehouse.db import connect, fetch_all_dicts, fetch_one_dict, jsonb
from cohortwarehouse.dbt_runner import run_dbt
from cohortwarehouse.settings import repo_root

log = logging.getLogger(__name__)


def write_release_report(run_id: str, release_id: str | None) -> str | None:
    with connect("transformer") as conn:
        run = fetch_one_dict(conn, "select * from ops.pipeline_run where run_id = %s", (run_id,))
        quality = fetch_all_dicts(
            conn, "select category, status, count(*) as n from ops.quality_result where run_id = %s "
                  "group by category, status order by 1, 2", (run_id,))
        batches = fetch_all_dicts(
            conn,
            "select b.batch_id, b.source_revision, b.manifest->'generator' as generator, "
            "jsonb_object_agg(f.file_key, jsonb_build_object('sha256', f.sha256, 'parsed', f.parsed_records, "
            "'accepted', f.accepted_records, 'quarantined', f.quarantined_records)) as files "
            "from ops.batch b join ops.batch_file f using (batch_id) "
            "where b.dataset_id = %s and b.source_revision <= %s group by 1, 2, 3 order by 2",
            (run["dataset_id"], run["target_revision"]))
        model_counts = fetch_all_dicts(
            conn,
            "select schemaname || '.' || relname as relation, n_live_tup as approx_rows from pg_stat_user_tables "
            "where schemaname in ('work_star', 'work_omop', 'work_bi') order by 1")
        vocab = fetch_one_dict(conn, "select vocabulary_version, is_test_only, file_hashes from ops.vocabulary_release "
                                     "where vocabulary_version = %s", (run["vocabulary_version"],))

    directory = repo_root() / "artifacts" / "releases" / (release_id or run_id)
    directory.mkdir(parents=True, exist_ok=True)
    docs_ok = True
    try:
        docs = run_dbt("docs generate", run_id=run_id, label="docs", git_sha=run["git_sha"] or "unknown")
        for name in ("manifest.json", "catalog.json", "index.html", "run_results.json"):
            source = docs.artifacts_path / name
            if source.is_file():
                (directory / name).write_bytes(source.read_bytes())
    except Exception as exc:  # noqa: BLE001 - recorded, not fatal
        docs_ok = False
        log.error("dbt docs generation failed: %s", exc)

    report = {
        "release_id": release_id,
        "run_id": run_id,
        "dataset_id": run["dataset_id"],
        "git_sha": run["git_sha"],
        "mode": run["mode"],
        "full_refresh_reason": run["full_refresh_reason"],
        "source": {"target_batch_id": run["target_batch_id"], "revision": run["target_revision"],
                   "as_of_date": str(run["as_of_date"]), "batches": batches},
        "vocabulary": vocab,
        "build_fingerprint": run["build_fingerprint"],
        "stage_timings_seconds": run["stage_timings"],
        "counts": run["counts"],
        "quality": quality,
        "candidate_model_row_estimates": model_counts,
        "runtime": {"python": platform.python_version(), "platform": platform.platform()},
        "docs_generated": docs_ok,
        "label": "Synthetic data - demonstration only",
    }
    (directory / "release_manifest.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    if release_id:
        with connect("publisher") as conn, conn.cursor() as cur:
            cur.execute(
                "insert into ops.release_event (dataset_id, release_id, run_id, event, detail) "
                "values (%s, %s, %s, %s, %s)",
                (run["dataset_id"], release_id, run_id, "docs_generated" if docs_ok else "docs_incomplete",
                 jsonb({"directory": str(directory.relative_to(repo_root()))})),
            )
            conn.commit()
    return str(directory)
