"""Load an OMOP vocabulary package (Athena download format) into the `vocab` schema (GOV-03).

Real Athena packages stay outside Git (licence terms vary per vocabulary). The repository ships
only a deliberately FICTIONAL test vocabulary (tests/fixtures/vocabulary) that exercises mapping
mechanics; it is flagged `is_test_only` and can never satisfy the release validation profile.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from psycopg import sql
from psycopg.types.json import Jsonb

from cohortwarehouse.db import connect
from cohortwarehouse.errors import ContractError
from cohortwarehouse.fingerprint import file_sha256
from cohortwarehouse.omop_ddl import load_ddl

log = logging.getLogger(__name__)

REQUIRED = ("concept", "vocabulary", "domain", "concept_class", "relationship", "concept_relationship")
OPTIONAL = ("concept_ancestor", "concept_synonym", "drug_strength")
TEST_MARKER = "TEST_ONLY_FICTIONAL_VOCABULARY.txt"


def _vocabulary_version(path: Path) -> str:
    with (path / "VOCABULARY.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE):
            if row.get("vocabulary_id") == "None":
                return row["vocabulary_version"]
    raise ContractError("VOCABULARY.csv lacks the 'None' row that carries the package version")


def load_vocabulary(path: str | Path, *, license_note: str) -> dict:
    path = Path(path)
    is_test = (path / TEST_MARKER).is_file()
    version = _vocabulary_version(path)
    if is_test and "FICTIONAL" not in version.upper():
        raise ContractError("a test-only vocabulary must carry FICTIONAL in its version label")
    if not is_test and "FICTIONAL" in version.upper():
        raise ContractError(f"vocabulary {version!r} looks fictional but has no {TEST_MARKER} marker")

    ddl = load_ddl()
    hashes: dict[str, str] = {}
    counts: dict[str, int] = {}
    with connect("admin") as conn, conn.cursor() as cur:
        cur.execute("select pg_advisory_xact_lock(hashtextextended('cohortwarehouse:vocabulary', 0))")
        for table in REQUIRED + OPTIONAL:
            file_path = path / f"{table.upper()}.csv"
            if not file_path.is_file():
                if table in REQUIRED:
                    raise ContractError(f"vocabulary package lacks {file_path.name}")
                cur.execute(sql.SQL("truncate {}").format(sql.Identifier("vocab", table)))
                counts[table] = 0
                continue
            hashes[file_path.name] = file_sha256(file_path)
            cur.execute(sql.SQL("truncate {}").format(sql.Identifier("vocab", table)))
            columns = [c.name for c in ddl[table].columns]
            with file_path.open(encoding="utf-8", newline="") as handle:
                header = handle.readline().rstrip("\r\n").split("\t")
                if [h.lower() for h in header] != columns:
                    raise ContractError(f"{file_path.name}: header {header} does not match CDM columns {columns}")
                copy_sql = sql.SQL(
                    "copy {} ({}) from stdin with (format csv, delimiter E'\\t', quote E'\\b', null '')"
                ).format(sql.Identifier("vocab", table), sql.SQL(", ").join(map(sql.Identifier, columns)))
                with cur.copy(copy_sql) as copy:
                    while chunk := handle.read(1 << 20):
                        copy.write(chunk)
            cur.execute(sql.SQL("select count(*) from {}").format(sql.Identifier("vocab", table)))
            counts[table] = cur.fetchone()[0]
        cur.execute("analyze vocab.concept")
        cur.execute("analyze vocab.concept_relationship")
        cur.execute("update ops.vocabulary_release set is_current = false where is_current")
        cur.execute(
            """
            insert into ops.vocabulary_release (vocabulary_version, source_kind, is_test_only, file_hashes,
                row_counts, license_note, is_current)
            values (%s, %s, %s, %s, %s, %s, true)
            on conflict (vocabulary_version) do update
               set file_hashes = excluded.file_hashes, row_counts = excluded.row_counts,
                   license_note = excluded.license_note, loaded_at = now(), is_current = true,
                   source_kind = excluded.source_kind, is_test_only = excluded.is_test_only
            """,
            (version, "test_fictional" if is_test else "athena", is_test, Jsonb(hashes), Jsonb(counts), license_note),
        )
        conn.commit()
    log.info("loaded vocabulary %s (test_only=%s): %s", version, is_test, counts)
    return {"vocabulary_version": version, "is_test_only": is_test, "row_counts": counts}
