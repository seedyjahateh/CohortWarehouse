"""Retention policy (Section 10): dry run by default; never removes what a retained release needs.

* Releases: keep current, previous and report-pinned releases; others may be dropped.
* Raw batches and quarantine payloads: 30 days, except batches required to rebuild a retained release
  (its latest full snapshot and every later scoped batch up to its revision) or the latest input state.
* Audit metadata (load attempts, alerts, quality results of runs without a retained release): 90 days.
"""

from __future__ import annotations

import logging

from psycopg import sql

from cohortwarehouse.db import connect, fetch_all_dicts, warehouse_write_lock
from cohortwarehouse.settings import pipeline_config

log = logging.getLogger(__name__)


def _plan(conn, dataset_id: str) -> dict:
    policy = pipeline_config()["retention"]
    raw_days, audit_days = policy["raw_and_quarantine_days"], policy["audit_metadata_days"]

    releases = fetch_all_dicts(
        conn,
        """
        select r.release_id, r.source_revision, r.star_schema, r.omop_schema, r.bi_schema, r.status,
               (c.release_id = r.release_id) as is_current,
               (c.previous_release_id = r.release_id) as is_previous,
               exists (select 1 from ops.report_pin p where p.release_id = r.release_id) as is_pinned
        from ops.release r
        left join ops.current_release c on c.dataset_id = r.dataset_id
        where r.dataset_id = %s
        order by r.release_number
        """,
        (dataset_id,),
    )
    keep, drop = [], []
    for r in releases:
        if r["status"] != "published":
            continue
        reasons = [label for flag, label in ((r["is_current"], "current"), (r["is_previous"], "previous"),
                                             (r["is_pinned"], "report_pinned")) if flag]
        (keep if reasons else drop).append({**r, "keep_reasons": reasons})

    retained_revisions = [r["source_revision"] for r in keep]
    latest = fetch_all_dicts(conn, "select max(source_revision) as rev from ops.batch where dataset_id = %s",
                             (dataset_id,))[0]["rev"]
    if latest is not None:
        retained_revisions.append(latest)

    required: set[str] = set()
    for revision in retained_revisions:
        rows = fetch_all_dicts(
            conn,
            """
            with full_snapshot as (
                select max(source_revision) as rev from ops.batch
                where dataset_id = %(d)s and replacement_mode = 'full' and source_revision <= %(r)s
            )
            select batch_id from ops.batch, full_snapshot
            where dataset_id = %(d)s and source_revision between full_snapshot.rev and %(r)s
            """,
            {"d": dataset_id, "r": revision},
        )
        required.update(r["batch_id"] for r in rows)

    expired_batches = fetch_all_dicts(
        conn,
        """
        select batch_id, source_revision, loaded_at from ops.batch
        where dataset_id = %s and loaded_at < now() - make_interval(days => %s)
        order by source_revision
        """,
        (dataset_id, raw_days),
    )
    return {
        "dataset_id": dataset_id,
        "policy": policy,
        "releases_kept": [{"release_id": r["release_id"], "reasons": r["keep_reasons"]} for r in keep],
        "releases_droppable": [r["release_id"] for r in drop],
        "_drop_release_rows": drop,
        "raw_batches_required": sorted(required),
        "raw_batches_expired_and_droppable": [b["batch_id"] for b in expired_batches
                                              if b["batch_id"] not in required],
        "raw_batches_expired_but_required": [b["batch_id"] for b in expired_batches if b["batch_id"] in required],
        "audit_retention_days": audit_days,
    }


def cleanup(*, dataset_id: str, apply: bool = False) -> dict:
    with connect("admin") as conn:
        plan = _plan(conn, dataset_id)
    drop_rows = plan.pop("_drop_release_rows")
    plan["mode"] = "apply" if apply else "dry_run"
    if not apply:
        return plan

    with warehouse_write_lock("admin", dataset_id), connect("admin") as conn, conn.cursor() as cur:
        # Re-plan under the lock: the current/previous pointers may have moved.
        fresh = _plan(conn, dataset_id)
        if sorted(fresh["releases_droppable"]) != sorted(plan["releases_droppable"]):
            drop_rows = fresh["_drop_release_rows"]
        for release in drop_rows:
            for schema in (release["star_schema"], release["omop_schema"], release["bi_schema"]):
                cur.execute(sql.SQL("drop schema if exists {} cascade").format(sql.Identifier(schema)))
            cur.execute("update ops.release set status = 'dropped', dropped_at = now() where release_id = %s",
                        (release["release_id"],))
            cur.execute(
                "insert into ops.release_event (dataset_id, release_id, event, detail) "
                "values (%s, %s, 'dropped', '{\"reason\": \"retention\"}')",
                (dataset_id, release["release_id"]),
            )
        for batch_id in fresh["raw_batches_expired_and_droppable"]:
            for table in ("patients", "encounters", "conditions", "medications", "observations", "organizations"):
                cur.execute(sql.SQL("delete from {} where _batch_id = %s").format(sql.Identifier("raw", table)),
                            (batch_id,))
            cur.execute("update ops.quarantine set payload = null where batch_id = %s", (batch_id,))
        cur.execute(
            "update ops.quarantine set payload = null "
            "where ingested_at < now() - make_interval(days => %s) and payload is not null",
            (plan["policy"]["raw_and_quarantine_days"],),
        )
        days = plan["audit_retention_days"]
        cur.execute("delete from ops.load_attempt where started_at < now() - make_interval(days => %s)", (days,))
        cur.execute("delete from ops.alert_event where at < now() - make_interval(days => %s)", (days,))
        cur.execute(
            """
            delete from ops.quality_result q
             where q.checked_at < now() - make_interval(days => %s)
               and not exists (select 1 from ops.release r where r.run_id = q.run_id and r.status = 'published')
            """,
            (days,),
        )
        conn.commit()
    log.info("retention applied for %s: dropped releases %s", dataset_id, [r["release_id"] for r in drop_rows])
    return {**plan, "applied": True}
