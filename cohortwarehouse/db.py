"""PostgreSQL connections and the warehouse write lock."""

from __future__ import annotations

import contextlib
import datetime as dt
import decimal
import json
import logging
from collections.abc import Iterator

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from cohortwarehouse.errors import ConcurrencyError, TransientError
from cohortwarehouse.settings import database_target

log = logging.getLogger(__name__)

# Namespaced advisory-lock key shared by the CLI and Airflow tasks (Section 9.3).
WRITE_LOCK_NAMESPACE = "cohortwarehouse:warehouse-write"


def connect(role: str, *, autocommit: bool = False) -> psycopg.Connection:
    target = database_target(role)
    try:
        conn = psycopg.connect(**target.conninfo(), autocommit=autocommit)
    except psycopg.OperationalError as exc:
        # Never echo the password-bearing conninfo; the server message itself carries no secret.
        message = str(exc).replace(target.password, "***") if target.password else str(exc)
        raise TransientError(f"cannot connect to {target.redacted()}: {message.strip()}") from None
    with conn.cursor() as cur:
        cur.execute("set time zone 'UTC'")
    if not autocommit:
        conn.commit()
    return conn


@contextlib.contextmanager
def warehouse_write_lock(role: str, dataset_id: str, *, wait: bool = False) -> Iterator[None]:
    """Session-level advisory lock held on a dedicated connection for the command's duration."""
    conn = connect(role, autocommit=True)
    key = f"{WRITE_LOCK_NAMESPACE}:{dataset_id}"
    try:
        with conn.cursor() as cur:
            if wait:
                cur.execute("select pg_advisory_lock(hashtextextended(%s, 0))", (key,))
                acquired = True
            else:
                cur.execute("select pg_try_advisory_lock(hashtextextended(%s, 0))", (key,))
                acquired = cur.fetchone()[0]
        if not acquired:
            raise ConcurrencyError(f"another pipeline process holds the write lock for dataset {dataset_id!r}")
        log.debug("acquired write lock %s", key)
        yield
    finally:
        conn.close()  # closing the session releases the advisory lock


def _json_default(value):
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, dt.date | dt.datetime):
        return value.isoformat()
    return str(value)


def jsonb(value) -> Jsonb:
    """Jsonb adapter tolerant of Decimal/date values coming back from queries."""
    return Jsonb(value, dumps=lambda obj: json.dumps(obj, default=_json_default))


def ident(*parts: str) -> sql.Identifier:
    return sql.Identifier(*parts)


def fetch_all_dicts(conn: psycopg.Connection, query, params=None) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, params)
        return list(cur.fetchall())


def fetch_one_dict(conn: psycopg.Connection, query, params=None) -> dict | None:
    rows = fetch_all_dicts(conn, query, params)
    return rows[0] if rows else None
