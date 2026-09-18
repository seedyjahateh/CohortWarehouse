"""Transactional publication, verification and restore (Section 9.4, NFR-09, NFR-10).

A release is three immutable schemas (star_rNNNN, omop_rNNNN, bi_rNNNN) copied from validated candidates.
Copies, checksum comparison, stable-view switching and ops.current_release all happen in ONE PostgreSQL
transaction: readers see either the previous release or the new one, never a mixture.
"""

from __future__ import annotations

import logging
import os
import time

import psycopg
from psycopg import sql

from cohortwarehouse.db import connect, fetch_all_dicts, fetch_one_dict, jsonb, warehouse_write_lock
from cohortwarehouse.errors import PublicationError
from cohortwarehouse.omop_ddl import POPULATED_TABLES, VOCABULARY_TABLES, clinical_tables
from cohortwarehouse.pipeline import build_fingerprint

log = logging.getLogger(__name__)

MARTS = {"star": "work_star", "omop": "work_omop", "bi": "work_bi"}
READERS = {"bi": "cwr_bi_reader", "omop": "cwr_omop_reader"}
INJECT_ENV = "CW_INJECT_PUBLISH_FAILURE"


def _base_tables(cur: psycopg.Cursor, schema: str) -> list[str]:
    cur.execute(
        "select table_name from information_schema.tables where table_schema = %s and table_type = 'BASE TABLE' "
        "and table_name not like '\\_%%' order by table_name",
        (schema,),
    )
    return [r[0] for r in cur.fetchall()]


def _columns(cur: psycopg.Cursor, schema: str, table: str) -> list[str]:
    cur.execute(
        "select column_name from information_schema.columns where table_schema = %s and table_name = %s "
        "order by ordinal_position",
        (schema, table),
    )
    return [r[0] for r in cur.fetchall()]


def table_checksum(cur: psycopg.Cursor, schema: str, table: str, columns: list[str]) -> dict:
    """Order-independent content checksum: row count plus the sum of 60-bit row-hash prefixes."""
    row = sql.SQL("row({})").format(sql.SQL(", ").join(map(sql.Identifier, columns)))
    cur.execute(
        sql.SQL(
            "select count(*), coalesce(sum(('x' || substr(md5({row}::text), 1, 15))::bit(60)::bigint::numeric), 0) "
            "from {table}"
        ).format(row=row, table=sql.Identifier(schema, table))
    )
    count, digest = cur.fetchone()
    return {"rows": count, "digest": str(digest)}


def _copy_table(cur, source_schema: str, target_schema: str, table: str, *, create_like: bool) -> dict:
    target_columns = _columns(cur, target_schema, table) if not create_like else None
    if create_like:
        cur.execute(
            sql.SQL("create table {} (like {} including all)").format(
                sql.Identifier(target_schema, table), sql.Identifier(source_schema, table)
            )
        )
        target_columns = _columns(cur, target_schema, table)
    source_columns = set(_columns(cur, source_schema, table))
    if set(target_columns) != source_columns:
        raise PublicationError(
            f"{source_schema}.{table} columns {sorted(source_columns)} do not match release table "
            f"{target_schema}.{table} {sorted(target_columns)}"
        )
    column_list = sql.SQL(", ").join(map(sql.Identifier, target_columns))
    cur.execute(
        sql.SQL("insert into {} ({cols}) select {cols} from {}").format(
            sql.Identifier(target_schema, table), sql.Identifier(source_schema, table), cols=column_list
        )
    )
    source_sum = table_checksum(cur, source_schema, table, target_columns)
    target_sum = table_checksum(cur, target_schema, table, target_columns)
    if source_sum != target_sum:
        raise PublicationError(f"checksum mismatch copying {source_schema}.{table}: {source_sum} != {target_sum}")
    return {**target_sum, "columns": target_columns}


def _point_views(cur: psycopg.Cursor, release: dict) -> None:
    """Replace every stable view so it points at the given release (inside the caller's transaction)."""
    for mart in MARTS:
        release_schema = release[f"{mart}_schema"]
        cur.execute(
            "select table_name from information_schema.views where table_schema = %s", (mart,)
        )
        for (view,) in cur.fetchall():
            cur.execute(sql.SQL("drop view {}").format(sql.Identifier(mart, view)))
        for table in _base_tables(cur, release_schema):
            cols = sql.SQL(", ").join(map(sql.Identifier, _columns(cur, release_schema, table)))
            cur.execute(
                sql.SQL("create view {} as select {} from {}").format(
                    sql.Identifier(mart, table), cols, sql.Identifier(release_schema, table)
                )
            )
        if mart == "omop":
            for vocab_table in VOCABULARY_TABLES:
                cur.execute(
                    sql.SQL("create view {} as select * from {}").format(
                        sql.Identifier("omop", vocab_table), sql.Identifier("vocab", vocab_table)
                    )
                )
        if mart in READERS:
            cur.execute(sql.SQL("grant usage on schema {} to {}").format(
                sql.Identifier(mart), sql.Identifier(READERS[mart])))
            cur.execute(sql.SQL("grant select on all tables in schema {} to {}").format(
                sql.Identifier(mart), sql.Identifier(READERS[mart])))


def _maybe_inject(stage: str) -> None:
    if os.environ.get(INJECT_ENV) == stage:
        raise PublicationError(f"injected publication failure at stage {stage!r} ({INJECT_ENV})")


def _record_event(dataset_id: str, event: str, *, release_id=None, run_id=None, detail=None) -> None:
    with connect("publisher") as conn, conn.cursor() as cur:
        cur.execute(
            "insert into ops.release_event (dataset_id, release_id, run_id, event, detail) values (%s, %s, %s, %s, %s)",
            (dataset_id, release_id, run_id, event, jsonb(detail or {})),
        )
        conn.commit()


def publish(run_id: str) -> dict:
    started = time.perf_counter()
    with connect("publisher") as conn:
        run = fetch_one_dict(conn, "select * from ops.pipeline_run where run_id = %s", (run_id,))
    if run is None:
        raise PublicationError(f"unknown run {run_id}")
    dataset_id = run["dataset_id"]

    with warehouse_write_lock("publisher", dataset_id):
        try:
            result = _publish_locked(run_id)
        except Exception as exc:
            _record_event(dataset_id, "publish_failed", run_id=run_id,
                          detail={"error": f"{type(exc).__name__}: {exc}"[:2000]})
            raise
    result["seconds"] = round(time.perf_counter() - started, 3)
    return result


def _publish_locked(run_id: str) -> dict:
    with connect("publisher") as conn, conn.cursor() as cur:
        run = fetch_one_dict(conn, "select * from ops.pipeline_run where run_id = %s for update", (run_id,))
        dataset_id = run["dataset_id"]
        # ---- refuse anything that is not exactly the validated candidate (Section 9.4)
        if run["status"] != "validated":
            raise PublicationError(f"run {run_id} is {run['status']}; only validated runs can be published")
        if run["mode"] == "validation_only":
            raise PublicationError("validation-only builds are for inspection and can never be published")
        state = fetch_one_dict(conn, "select * from ops.build_state where dataset_id = %s", (dataset_id,))
        if state is None or state["run_id"] != run_id:
            raise PublicationError(
                f"candidate schemas were rebuilt by run {state and state['run_id']} after {run_id} was validated"
            )
        vocab = fetch_one_dict(conn, "select vocabulary_version from ops.vocabulary_release where is_current")
        if vocab is None or vocab["vocabulary_version"] != run["vocabulary_version"]:
            raise PublicationError("current vocabulary differs from the one this run was built and validated with")
        if build_fingerprint(run["vocabulary_version"]) != run["build_fingerprint"]:
            raise PublicationError("transformation code/seeds changed since validation; rebuild and revalidate")
        current = fetch_one_dict(
            conn,
            "select r.* from ops.current_release c join ops.release r using (release_id) where c.dataset_id = %s",
            (dataset_id,),
        )
        if current and run["target_revision"] < current["source_revision"]:
            raise PublicationError(
                f"run revision {run['target_revision']} is older than current release {current['release_id']} "
                f"(revision {current['source_revision']}); use `restore` to go back"
            )
        quality = fetch_one_dict(
            conn,
            """
            select count(*) filter (where status = 'pass') as passed,
                   count(*) filter (where status in ('fail', 'skip') and severity = 'blocking') as failed,
                   count(*) filter (where status = 'warn') as warned
            from ops.quality_result where run_id = %s
            """,
            (run_id,),
        )
        if quality["failed"] or not quality["passed"]:
            raise PublicationError(f"quality results for {run_id} do not support publication: {quality}")

        cur.execute("select pg_advisory_xact_lock(hashtextextended('cohortwarehouse:release-number', 0))")
        cur.execute("select coalesce(max(release_number), 0) + 1 from ops.release")
        number = cur.fetchone()[0]
        release_id = f"r{number:04d}"
        schemas = {mart: f"{mart}_{release_id}" for mart in MARTS}
        checksums: dict[str, dict] = {}

        for schema in schemas.values():
            cur.execute(sql.SQL("create schema {}").format(sql.Identifier(schema)))

        # star and bi: structure copied from the validated candidates
        for mart in ("star", "bi"):
            for table in _base_tables(cur, MARTS[mart]):
                checksums[f"{schemas[mart]}.{table}"] = _copy_table(cur, MARTS[mart], schemas[mart], table,
                                                                   create_like=True)
        _maybe_inject("after_copy")

        # omop: official CDM DDL (all clinical tables; unpopulated ones stay empty), then the cw_ extras
        for table in clinical_tables().values():
            cur.execute(table.render(schemas["omop"]))
        for table in POPULATED_TABLES:
            checksums[f"{schemas['omop']}.{table}"] = _copy_table(cur, "work_omop", schemas["omop"], table,
                                                                 create_like=False)
        for table in ("cw_event_crosswalk", "cw_exclusion_ledger"):
            checksums[f"{schemas['omop']}.{table}"] = _copy_table(cur, "work_omop", schemas["omop"], table,
                                                                 create_like=True)

        # Key registry backup travels with the release (Section 8.4.8).
        cur.execute(
            sql.SQL("create table {} as select * from ops.entity_key_map where dataset_id = %s").format(
                sql.Identifier(schemas["star"], "_key_registry_backup")
            ),
            (dataset_id,),
        )

        # Release identity inside the BI release (Power BI reads it from the same schema it imports).
        cur.execute(
            sql.SQL(
                """
                update {} set release_id = %s, published_at_utc = now(), quality_checks_passed = %s,
                              quality_checks_failed = %s, quality_checks_warned = %s
                """
            ).format(sql.Identifier(schemas["bi"], "bi_release_status")),
            (release_id, quality["passed"], quality["failed"], quality["warned"]),
        )
        status_columns = _columns(cur, schemas["bi"], "bi_release_status")
        checksums[f"{schemas['bi']}.bi_release_status"] = {
            **table_checksum(cur, schemas["bi"], "bi_release_status", status_columns), "columns": status_columns
        }

        for mart, reader in READERS.items():
            cur.execute(sql.SQL("grant usage on schema {} to {}").format(sql.Identifier(schemas[mart]),
                                                                        sql.Identifier(reader)))
            cur.execute(sql.SQL("grant select on all tables in schema {} to {}").format(
                sql.Identifier(schemas[mart]), sql.Identifier(reader)))

        cur.execute(
            """
            insert into ops.release (release_id, release_number, dataset_id, run_id, source_revision, source_batch_id,
                as_of_date, vocabulary_version, build_fingerprint, git_sha, star_schema, omop_schema, bi_schema,
                table_checksums, validation_profile, status)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'published')
            """,
            (release_id, number, dataset_id, run_id, run["target_revision"], run["target_batch_id"],
             run["as_of_date"], run["vocabulary_version"], run["build_fingerprint"], run["git_sha"],
             schemas["star"], schemas["omop"], schemas["bi"],
             jsonb({k: {"rows": v["rows"], "digest": v["digest"]} for k, v in checksums.items()}),
             (run["counts"] or {}).get("validation_profile")),
        )
        release = {"release_id": release_id, **{f"{m}_schema": s for m, s in schemas.items()}}
        _point_views(cur, release)
        _maybe_inject("before_commit")
        cur.execute(
            """
            insert into ops.current_release (dataset_id, release_id, previous_release_id, reason)
            values (%s, %s, null, 'publish')
            on conflict (dataset_id) do update
               set previous_release_id = ops.current_release.release_id, release_id = excluded.release_id,
                   switched_at = now(), switched_by = session_user, reason = 'publish'
            """,
            (dataset_id, release_id),
        )
        cur.execute(
            "insert into ops.release_event (dataset_id, release_id, run_id, event, detail) "
            "values (%s, %s, %s, 'published', %s)",
            (dataset_id, release_id, run_id, jsonb({"tables": len(checksums)})),
        )
        cur.execute("update ops.pipeline_run set status = 'published', finished_at = now() where run_id = %s",
                    (run_id,))
        conn.commit()

    log.info("published %s from run %s (%d tables)", release_id, run_id, len(checksums))
    return {"release_id": release_id, "run_id": run_id, "schemas": schemas, "tables": len(checksums),
            "power_bi_release_schema": schemas["bi"]}


def verify_release_integrity(cur: psycopg.Cursor, release: dict) -> list[str]:
    problems = []
    for qualified, recorded in release["table_checksums"].items():
        schema, table = qualified.split(".", 1)
        cur.execute("select to_regclass(%s)", (f'"{schema}"."{table}"',))
        if cur.fetchone()[0] is None:
            problems.append(f"{qualified} is missing")
            continue
        actual = table_checksum(cur, schema, table, _columns(cur, schema, table))
        if actual["rows"] != recorded["rows"] or actual["digest"] != recorded["digest"]:
            problems.append(f"{qualified} changed: recorded {recorded}, actual {actual}")
    return problems


def validate_release(release_id: str) -> dict:
    with connect("publisher") as conn, conn.cursor() as cur:
        release = fetch_one_dict(conn, "select * from ops.release where release_id = %s", (release_id,))
        if release is None:
            raise PublicationError(f"unknown release {release_id}")
        if release["status"] != "published":
            return {"release_id": release_id, "ok": False, "problems": [f"release status is {release['status']}"]}
        problems = verify_release_integrity(cur, release)
        current = fetch_one_dict(conn, "select release_id from ops.current_release where dataset_id = %s",
                                 (release["dataset_id"],))
        if current and current["release_id"] == release_id:
            cur.execute("select release_id from bi.bi_release_status")
            shown = [r[0] for r in cur.fetchall()]
            if shown != [release_id]:
                problems.append(f"stable bi views expose {shown}, expected [{release_id}]")
        conn.rollback()
    return {"release_id": release_id, "ok": not problems, "is_current": bool(current and
            current["release_id"] == release_id), "tables_verified": len(release["table_checksums"]),
            "problems": problems}


def restore(release_id: str, *, dataset_id: str | None = None, reason: str = "operator restore") -> dict:
    started = time.perf_counter()
    with connect("publisher") as conn:
        release = fetch_one_dict(conn, "select * from ops.release where release_id = %s", (release_id,))
    if release is None:
        raise PublicationError(f"unknown release {release_id}")
    if dataset_id and dataset_id != release["dataset_id"]:
        raise PublicationError(f"release {release_id} belongs to dataset {release['dataset_id']}")
    dataset_id = release["dataset_id"]
    if release["status"] != "published":
        raise PublicationError(f"release {release_id} is {release['status']} and cannot be restored")

    with warehouse_write_lock("publisher", dataset_id):
        try:
            with connect("publisher") as conn, conn.cursor() as cur:
                problems = verify_release_integrity(cur, release)
                if problems:
                    raise PublicationError(f"release {release_id} failed integrity verification: {problems}")
                _point_views(cur, release)
                cur.execute(
                    """
                    update ops.current_release
                       set previous_release_id = release_id, release_id = %s, switched_at = now(),
                           switched_by = session_user, reason = %s
                     where dataset_id = %s
                    """,
                    (release_id, f"restore: {reason}"[:500], dataset_id),
                )
                if cur.rowcount != 1:
                    raise PublicationError(f"dataset {dataset_id} has no current release to switch from")
                cur.execute(
                    "insert into ops.release_event (dataset_id, release_id, event, detail) "
                    "values (%s, %s, 'restored', %s)",
                    (dataset_id, release_id, jsonb({"reason": reason})),
                )
                conn.commit()
        except Exception as exc:
            _record_event(dataset_id, "restore_failed", release_id=release_id,
                          detail={"error": f"{type(exc).__name__}: {exc}"[:2000]})
            raise

    # Post-switch verification through the stable views (recheck cohort totals).
    with connect("publisher") as conn, conn.cursor() as cur:
        cur.execute("select release_id from bi.bi_release_status")
        shown = [r[0] for r in cur.fetchall()]
        cur.execute("select cohort_id, count(*) from bi.bi_cohort_membership group by cohort_id order by cohort_id")
        via_views = dict(cur.fetchall())
        cur.execute(sql.SQL("select cohort_id, count(*) from {} group by cohort_id order by cohort_id").format(
            sql.Identifier(release["bi_schema"], "bi_cohort_membership")))
        via_release = dict(cur.fetchall())
    if shown != [release_id] or via_views != via_release:
        raise PublicationError(f"post-restore verification failed: views show {shown}, {via_views} vs {via_release}")
    return {"restored_release_id": release_id, "dataset_id": dataset_id, "cohort_counts": via_views,
            "seconds": round(time.perf_counter() - started, 3)}


def list_releases(dataset_id: str | None = None) -> dict:
    with connect("publisher") as conn:
        releases = fetch_all_dicts(
            conn,
            """
            select r.release_id, r.dataset_id, r.run_id, r.source_batch_id, r.source_revision, r.as_of_date,
                   r.vocabulary_version, r.git_sha, r.status, r.published_at, r.bi_schema,
                   (c.release_id is not null) as is_current,
                   exists (select 1 from ops.report_pin p where p.release_id = r.release_id) as is_pinned
            from ops.release r
            left join ops.current_release c on c.release_id = r.release_id
            where %(dataset)s::text is null or r.dataset_id = %(dataset)s
            order by r.release_number
            """,
            {"dataset": dataset_id},
        )
        current = fetch_all_dicts(
            conn, "select * from ops.current_release where %(d)s::text is null or dataset_id = %(d)s", {"d": dataset_id}
        )
    return {"releases": releases, "current": current}


def pin_release(release_id: str, report_name: str, *, unpin: bool = False) -> dict:
    with connect("publisher") as conn, conn.cursor() as cur:
        if unpin:
            cur.execute("delete from ops.report_pin where release_id = %s and report_name = %s",
                        (release_id, report_name))
        else:
            cur.execute(
                "insert into ops.report_pin (release_id, report_name) values (%s, %s) on conflict do nothing",
                (release_id, report_name),
            )
        conn.commit()
    return {"release_id": release_id, "report": report_name, "pinned": not unpin}
