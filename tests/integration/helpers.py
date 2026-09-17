from __future__ import annotations

import contextlib
import os

from psycopg import sql

from cohortwarehouse.bootstrap import bootstrap
from cohortwarehouse.db import connect
from cohortwarehouse.vocabulary import load_vocabulary
from tests.conftest import VOCABULARY, pseudo_id

PROJECT_SCHEMAS = ("raw", "ops", "vocab", "omop_ddl_ref", "stg", "int", "seeds", "work_star", "work_omop", "work_bi",
                   "work_audit", "star", "omop", "bi")


def reset_warehouse() -> None:
    """Drop every project schema (including release schemas) and bootstrap from scratch. Disposable DBs only."""
    with connect("admin") as conn, conn.cursor() as cur:
        cur.execute(
            "select nspname from pg_namespace where nspname = any(%s) or nspname ~ '^(star|omop|bi)_r[0-9]{4}$'",
            (list(PROJECT_SCHEMAS),),
        )
        for (schema,) in cur.fetchall():
            cur.execute(sql.SQL("drop schema {} cascade").format(sql.Identifier(schema)))
        conn.commit()
    bootstrap()
    load_vocabulary(VOCABULARY, license_note="Fictional test-only vocabulary (tests)")


def query(sql_text: str, params=None, *, role: str = "admin") -> list[tuple]:
    with connect(role) as conn, conn.cursor() as cur:
        cur.execute(sql_text, params)
        rows = cur.fetchall() if cur.description else []
        conn.rollback()
        return rows


def memberships(schema: str, *, role: str = "admin") -> dict[str, set[str]]:
    rows = query(
        f'select m.cohort_id, s.patient_pseudo_id from "{schema}".bi_cohort_membership m '
        f'join "{schema}".bi_patient_snapshot s using (patient_key)',
        role=role,
    )
    result: dict[str, set[str]] = {"C1": set(), "C2": set(), "C3": set()}
    for cohort, pseudo in rows:
        result[cohort].add(pseudo)
    return result


def eligible(schema: str, *, role: str = "admin") -> set[str]:
    return {r[0] for r in query(f'select patient_pseudo_id from "{schema}".bi_patient_snapshot', role=role)}


def expected_sets(expected: dict, batch: str) -> tuple[dict[str, set[str]], set[str]]:
    step = expected["after_batch"][batch]
    cohorts = {c: {pseudo_id(n) for n in step[c]} for c in ("C1", "C2", "C3")}
    return cohorts, {pseudo_id(n) for n in step["eligible"]}


@contextlib.contextmanager
def env(**values):
    previous = {k: os.environ.get(k) for k in values}
    os.environ.update({k: v for k, v in values.items() if v is not None})
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# Documented audit/delivery metadata that legitimately differs between replays (docs/decisions/0004).
AUDIT_COLUMNS = {"source_batch_id", "source_record_number", "run_id", "candidate_built_at_utc", "published_at_utc",
                 "cdm_release_date", "release_id", "quality_checks_passed", "quality_checks_failed",
                 "quality_checks_warned", "git_sha", "source_revision", "source_delivered_at_utc",
                 "source_description", "source_release_date", "cdm_etl_reference"}


def snapshot_schema(schema: str) -> dict[str, list[tuple]]:
    """Sorted clinical content of every table in a schema, excluding documented audit columns."""
    content = {}
    with connect("admin") as conn, conn.cursor() as cur:
        cur.execute(
            "select table_name from information_schema.tables where table_schema = %s and table_type = 'BASE TABLE' "
            "and table_name not like '\\_%%'",
            (schema,),
        )
        for (table,) in cur.fetchall():
            cur.execute(
                "select column_name from information_schema.columns where table_schema = %s and table_name = %s "
                "order by ordinal_position",
                (schema, table),
            )
            columns = [c for (c,) in cur.fetchall() if c not in AUDIT_COLUMNS]
            cur.execute(sql.SQL("select {} from {}").format(
                sql.SQL(", ").join(map(sql.Identifier, columns)), sql.Identifier(schema, table)))
            content[table] = sorted(cur.fetchall(), key=repr)
        conn.rollback()
    return content
