"""Idempotent warehouse bootstrap: roles, schemas, ops tables, raw tables, CDM reference DDL, grants."""

from __future__ import annotations

import hashlib
import logging
import os

import psycopg
from psycopg import sql

from cohortwarehouse.contract import SourceContract, load_contract
from cohortwarehouse.db import connect
from cohortwarehouse.errors import ConfigurationError
from cohortwarehouse.omop_ddl import VOCABULARY_TABLES, load_ddl
from cohortwarehouse.settings import database_target, repo_root

log = logging.getLogger(__name__)

RAW_METADATA_COLUMNS = (
    ("_dataset_id", "text not null"),
    ("_batch_id", "text not null references ops.batch (batch_id)"),
    ("_file_sha256", "text not null"),
    ("_record_number", "integer not null"),
    ("_ingested_at", "timestamptz not null"),
    ("_row_fingerprint", "text not null"),
)

LOGIN_ROLES = {
    "loader": "cwr_loader",
    "transformer": "cwr_transformer",
    "publisher": "cwr_publisher",
    "bi_reader": "cwr_bi_reader",
    "omop_reader": "cwr_omop_reader",
}


def raw_table_statements(contract: SourceContract) -> list[sql.Composable]:
    statements: list[sql.Composable] = []
    for key, file_contract in contract.files.items():
        table = sql.Identifier("raw", key)
        column_defs = [sql.SQL("{} {}").format(sql.Identifier(n), sql.SQL(t)) for n, t in RAW_METADATA_COLUMNS]
        column_defs += [sql.SQL("{} text").format(sql.Identifier(c.raw_name)) for c in file_contract.loaded_columns]
        column_defs.append(sql.SQL("primary key (_batch_id, _record_number)"))
        statements.append(
            sql.SQL("create table if not exists {} ({})").format(table, sql.SQL(", ").join(column_defs))
        )
        # A contract revision may add optional columns; never drop or retype existing raw data.
        for c in file_contract.loaded_columns:
            statements.append(
                sql.SQL("alter table {} add column if not exists {} text").format(table, sql.Identifier(c.raw_name))
            )
        statements.append(
            sql.SQL("create index if not exists {} on {} (_batch_id, _row_fingerprint)").format(
                sql.Identifier(f"{key}_batch_fingerprint"), table
            )
        )
        if file_contract.patient_column:
            statements.append(
                sql.SQL("create index if not exists {} on {} ({}, _batch_id)").format(
                    sql.Identifier(f"{key}_patient_batch"),
                    table,
                    sql.Identifier(file_contract.patient_column.lower()),
                )
            )
    return statements


def _apply_file(conn: psycopg.Connection, relative: str) -> None:
    path = repo_root() / relative
    body = path.read_text(encoding="utf-8")
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    with conn.cursor() as cur:
        cur.execute(body)
        cur.execute(
            """
            insert into ops.schema_migration (filename, sha256) values (%s, %s)
            on conflict (filename) do update set sha256 = excluded.sha256, applied_at = now()
            """,
            (relative, digest),
        )
    log.info("applied %s", relative)


def _create_cdm_tables(conn: psycopg.Connection) -> None:
    ddl = load_ddl()
    with conn.cursor() as cur:
        for name, table in ddl.items():
            schema = "vocab" if name in VOCABULARY_TABLES else "omop_ddl_ref"
            cur.execute("select to_regclass(%s)", (f"{schema}.{name}",))
            if cur.fetchone()[0] is None:
                cur.execute(table.render(schema))
        # Lookup indexes the mapping models rely on (the official DDL ships them separately).
        cur.execute("create unique index if not exists concept_pk on vocab.concept (concept_id)")
        cur.execute("create index if not exists concept_code_lookup on vocab.concept (vocabulary_id, concept_code)")
        cur.execute(
            "create index if not exists concept_relationship_lookup "
            "on vocab.concept_relationship (concept_id_1, relationship_id)"
        )


def _ensure_login_roles(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        for stage, group in LOGIN_ROLES.items():
            target = database_target(stage)
            if not target.password:
                raise ConfigurationError(f"CW_{stage.upper()}_PASSWORD must be set to create login role {target.user}")
            cur.execute("select 1 from pg_roles where rolname = %s", (target.user,))
            verb = "alter" if cur.fetchone() else "create"
            cur.execute(
                sql.SQL("{} role {} with login password {} nosuperuser nocreatedb nocreaterole noinherit").format(
                    sql.SQL(verb), sql.Identifier(target.user), sql.Literal(target.password)
                )
            )
            cur.execute(sql.SQL("grant {} to {}").format(sql.Identifier(group), sql.Identifier(target.user)))
            # NOINHERIT logins do not inherit CONNECT from the group, and the login check happens
            # before the session switches role, so CONNECT is granted to the login itself.
            cur.execute(
                sql.SQL("grant connect on database {} to {}").format(
                    sql.Identifier(target.dbname), sql.Identifier(target.user)
                )
            )
            # Sessions start as the group role, so objects are group-owned (see 010 file header).
            cur.execute(
                sql.SQL("alter role {} set role to {}").format(sql.Identifier(target.user), sql.Identifier(group))
            )
            cur.execute(sql.SQL("alter role {} set timezone to 'UTC'").format(sql.Identifier(target.user)))


def bootstrap(*, create_login_roles: bool = True) -> None:
    contract = load_contract()
    with connect("admin") as conn:
        with conn.cursor() as cur:
            cur.execute("select current_setting('server_version_num')::int")
            version = cur.fetchone()[0]
            if version // 10000 != 16:
                raise ConfigurationError(f"PostgreSQL 16 is required; server reports {version}")
            # Serialise concurrent bootstraps.
            cur.execute("select pg_advisory_xact_lock(hashtextextended('cohortwarehouse:bootstrap', 0))")
            cur.execute("create schema if not exists ops")
            cur.execute(
                "create table if not exists ops.schema_migration (filename text primary key, "
                "sha256 text not null, applied_at timestamptz not null default now())"
            )
        _apply_file(conn, "sql/bootstrap/010_roles_and_schemas.sql")
        _apply_file(conn, "sql/bootstrap/020_ops.sql")
        with conn.cursor() as cur:
            for statement in raw_table_statements(contract):
                cur.execute(statement)
        _create_cdm_tables(conn)
        _apply_file(conn, "sql/bootstrap/090_grants.sql")
        if create_login_roles and os.environ.get("CW_SKIP_LOGIN_ROLES") != "1":
            _ensure_login_roles(conn)
        conn.commit()
    log.info("bootstrap complete")
