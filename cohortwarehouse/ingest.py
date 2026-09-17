"""Raw ingestion (Section 5.1).

One PostgreSQL transaction per batch: the batch row, scope, every file's accepted rows (COPY),
quarantine records and reconciliation counts commit together or not at all. A failure can never
leave a batch looking complete with files missing.
"""

from __future__ import annotations

import contextlib
import csv
import datetime as dt
import json
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from cohortwarehouse.contract import (
    REQUIRED_FILE_KEYS,
    FileContract,
    SourceContract,
    check_header,
    load_contract,
    validate_value,
)
from cohortwarehouse.db import connect, fetch_one_dict, warehouse_write_lock
from cohortwarehouse.errors import CohortWarehouseError, ContractError
from cohortwarehouse.fingerprint import row_fingerprint
from cohortwarehouse.manifest import Manifest, load_manifest, preflight

log = logging.getLogger(__name__)

# Abort (rather than quarantine) when a file is systematically broken: a wrong delimiter or
# encoding would otherwise "succeed" with every row quarantined.
QUARANTINE_ABORT_MIN_ROWS = 50
QUARANTINE_ABORT_FRACTION = 0.20

# Natural keys that must be unique within one delivered file.
UNIQUE_NATURAL_KEYS = {"patients": "id", "encounters": "id", "organizations": "id"}


@dataclass
class FileResult:
    file_key: str
    parsed: int = 0
    accepted: int = 0
    quarantined: int = 0
    seconds: float = 0.0


@dataclass
class IngestResult:
    batch_id: str
    dataset_id: str
    outcome: str  # loaded | already_loaded
    files: dict[str, FileResult] = field(default_factory=dict)

    def summary(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "dataset_id": self.dataset_id,
            "outcome": self.outcome,
            "files": {
                k: {"parsed": v.parsed, "accepted": v.accepted, "quarantined": v.quarantined}
                for k, v in self.files.items()
            },
        }


@dataclass
class _Quarantined:
    record_number: int
    reason: str
    detail: str | None
    fingerprint: str | None
    payload: list[str] | dict


@contextlib.contextmanager
def _open_records(path: Path) -> Iterator[tuple[list[str], Iterator[list[str]]]]:
    """Yield (header, record iterator); decoding/structure errors become contract errors."""
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, strict=True)
            header = next(reader, None)
            if header is None:
                raise ContractError(
                    f"{path.name}: file is empty (a header row is required even with zero records)"
                )
            yield header, reader
    except UnicodeDecodeError as exc:
        raise ContractError(f"{path.name}: not valid UTF-8 ({exc.reason} at byte {exc.start})") from None
    except csv.Error as exc:
        raise ContractError(f"{path.name}: unrecoverable CSV structure error: {exc}") from None


def _record_attempt_start(manifest_path: Path) -> int | None:
    try:
        with connect("loader", autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(
                "insert into ops.load_attempt (manifest_path) values (%s) returning attempt_id",
                (str(manifest_path),),
            )
            return cur.fetchone()[0]
    except CohortWarehouseError:
        raise
    except psycopg.Error:
        log.exception("could not record load attempt")
        return None


def _record_attempt_end(attempt_id: int | None, manifest: Manifest | None, outcome: str, exc=None) -> None:
    if attempt_id is None:
        return
    with connect("loader", autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            """
            update ops.load_attempt
               set finished_at = now(), outcome = %s, batch_id = %s, dataset_id = %s,
                   manifest_sha256 = %s, error_class = %s, error_message = %s
             where attempt_id = %s
            """,
            (
                outcome,
                manifest.batch_id if manifest else None,
                manifest.dataset_id if manifest else None,
                manifest.sha256 if manifest else None,
                type(exc).__name__ if exc else None,
                str(exc)[:2000] if exc else None,
                attempt_id,
            ),
        )


def _check_batch_sequence(conn: psycopg.Connection, manifest: Manifest) -> bool:
    """Return True when this exact manifest is already loaded (idempotent replay)."""
    existing = fetch_one_dict(
        conn, "select manifest_sha256, dataset_id from ops.batch where batch_id = %s", (manifest.batch_id,)
    )
    if existing:
        if existing["manifest_sha256"] == manifest.sha256:
            return True
        raise ContractError(
            f"batch {manifest.batch_id} was already loaded from a different manifest; "
            "a batch ID can never be reused for different content"
        )
    latest = fetch_one_dict(
        conn,
        "select max(source_revision) as rev from ops.batch where dataset_id = %s",
        (manifest.dataset_id,),
    )
    if latest and latest["rev"] is not None and manifest.source_revision <= latest["rev"]:
        raise ContractError(
            f"source_revision {manifest.source_revision} is not after the latest loaded revision "
            f"{latest['rev']} for dataset {manifest.dataset_id}; revisions must be monotonic"
        )
    if manifest.replacement_mode == "scoped":
        full = fetch_one_dict(
            conn,
            "select 1 as ok from ops.batch where dataset_id = %s and replacement_mode = 'full' limit 1",
            (manifest.dataset_id,),
        )
        if not full:
            raise ContractError("a scoped batch requires an earlier full snapshot for the dataset")
    return False


def _load_file(
    cur: psycopg.Cursor,
    manifest: Manifest,
    file_contract: FileContract,
    ingested_at: dt.datetime,
    scope: frozenset[str] | None,
) -> FileResult:
    started = time.perf_counter()
    path = manifest.batch_dir / file_contract.filename
    declared = manifest.files[file_contract.key]
    result = FileResult(file_contract.key)
    quarantined: list[_Quarantined] = []
    loaded = file_contract.loaded_columns
    patient_col = file_contract.patient_column

    with _open_records(path) as (header, reader):
        header_check = check_header(file_contract, header)
        positions = header_check.positions
        width = len(header)
        target = sql.Identifier("raw", file_contract.key)
        columns = sql.SQL(", ").join(
            sql.Identifier(n)
            for n in ["_dataset_id", "_batch_id", "_file_sha256", "_record_number", "_ingested_at",
                      "_row_fingerprint", *(c.raw_name for c in loaded)]
        )
        copy_stmt = sql.SQL("copy {} ({}) from stdin").format(target, columns)
        with cur.copy(copy_stmt) as copy:
            for fields in reader:
                result.parsed += 1
                record_number = result.parsed
                if len(fields) != width:
                    quarantined.append(
                        _Quarantined(record_number, "field_count_mismatch",
                                     f"expected {width} fields, found {len(fields)}", None, fields)
                    )
                    continue
                values = [
                    (fields[positions[c.name]] or None) if c.name in positions else None for c in loaded
                ]
                fingerprint = row_fingerprint(file_contract.key, values)
                reason = None
                for column, value in zip(loaded, values, strict=True):
                    reason = validate_value(column, value)
                    if reason:
                        break
                if reason is None and scope is not None and patient_col:
                    patient = values[[c.name for c in loaded].index(patient_col)]
                    if patient not in scope:
                        reason = "patient_out_of_scope"
                if reason:
                    quarantined.append(
                        _Quarantined(record_number, reason.split(":")[0], reason, fingerprint,
                                     {c.name: v for c, v in zip(loaded, values, strict=True)})
                    )
                    continue
                copy.write_row(
                    [manifest.dataset_id, manifest.batch_id, declared["sha256"], record_number, ingested_at,
                     fingerprint, *values]
                )
                result.accepted += 1

    if result.parsed != declared["records"]:
        raise ContractError(
            f"{file_contract.filename}: manifest declares {declared['records']} records but "
            f"{result.parsed} were parsed; refusing to guess which rows shifted"
        )

    # Duplicate natural keys inside one file are ambiguous: quarantine every copy.
    unique_key = UNIQUE_NATURAL_KEYS.get(file_contract.key)
    if unique_key and result.accepted:
        cur.execute(
            sql.SQL(
                """
                delete from {table} t
                 using (select {key} from {table} where _batch_id = %s group by {key} having count(*) > 1) d
                 where t._batch_id = %s and t.{key} = d.{key}
                returning t._record_number, t._row_fingerprint, t.{key}
                """
            ).format(table=sql.Identifier("raw", file_contract.key), key=sql.Identifier(unique_key)),
            (manifest.batch_id, manifest.batch_id),
        )
        for record_number, fingerprint, key_value in cur.fetchall():
            quarantined.append(
                _Quarantined(record_number, "duplicate_natural_key", f"{unique_key}={key_value}", fingerprint,
                             {unique_key: key_value})
            )
            result.accepted -= 1

    result.quarantined = len(quarantined)
    if (
        result.quarantined >= QUARANTINE_ABORT_MIN_ROWS
        and result.quarantined > QUARANTINE_ABORT_FRACTION * max(result.parsed, 1)
    ):
        raise ContractError(
            f"{file_contract.filename}: {result.quarantined} of {result.parsed} records failed the contract; "
            "the file looks systematically malformed, so the batch is rejected instead of quarantined"
        )
    if quarantined:
        with cur.copy(
            "copy ops.quarantine (dataset_id, batch_id, file_key, record_number, file_sha256, reason, detail, "
            "row_fingerprint, payload, ingested_at) from stdin"
        ) as copy:
            for q in quarantined:
                copy.write_row(
                    [manifest.dataset_id, manifest.batch_id, file_contract.key, q.record_number, declared["sha256"],
                     q.reason, q.detail, q.fingerprint, json.dumps(q.payload, ensure_ascii=False), ingested_at]
                )

    result.seconds = time.perf_counter() - started
    cur.execute(
        """
        insert into ops.batch_file (batch_id, file_key, filename, sha256, size_bytes, header, extra_columns,
            missing_optional_columns, unloaded_columns, declared_records, parsed_records, accepted_records,
            quarantined_records, load_seconds)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            manifest.batch_id, file_contract.key, file_contract.filename, declared["sha256"],
            path.stat().st_size, Jsonb(header), Jsonb(header_check.extra_columns),
            Jsonb(header_check.missing_optional_columns), Jsonb(header_check.unloaded_present_columns),
            declared["records"], result.parsed, result.accepted, result.quarantined, round(result.seconds, 3),
        ),
    )
    return result


def ingest(manifest_path: str | Path, contract: SourceContract | None = None) -> IngestResult:
    contract = contract or load_contract()
    manifest_path = Path(manifest_path)
    attempt_id = _record_attempt_start(manifest_path)
    manifest: Manifest | None = None
    try:
        manifest = load_manifest(manifest_path, contract)
        scope_accounting = preflight(manifest, contract)
        with warehouse_write_lock("loader", manifest.dataset_id), connect("loader") as conn:
            if _check_batch_sequence(conn, manifest):
                conn.rollback()
                _record_attempt_end(attempt_id, manifest, "already_loaded")
                log.info("batch %s already loaded with identical manifest; nothing to do", manifest.batch_id)
                return IngestResult(manifest.batch_id, manifest.dataset_id, "already_loaded")

            result = IngestResult(manifest.batch_id, manifest.dataset_id, "loaded")
            ingested_at = dt.datetime.now(dt.UTC)
            generator = manifest.document["generator"]
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into ops.batch (batch_id, dataset_id, source_revision, as_of_date, delivered_at,
                        delivery_kind, replacement_mode, manifest, manifest_sha256, generator_name,
                        generator_version, synthetic, scope_accounting)
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        manifest.batch_id, manifest.dataset_id, manifest.source_revision, manifest.as_of,
                        manifest.delivered, manifest.document.get("delivery_kind", "manual"),
                        manifest.replacement_mode, Jsonb(manifest.document), manifest.sha256,
                        generator["name"], generator["version"], True, Jsonb(scope_accounting),
                    ),
                )
                scope = None
                if manifest.replacement_mode == "scoped":
                    scope = frozenset(manifest.patient_scope)
                    with cur.copy("copy ops.batch_scope_patient (batch_id, patient_id) from stdin") as copy:
                        for patient_id in sorted(scope):
                            copy.write_row([manifest.batch_id, patient_id])
                for key in REQUIRED_FILE_KEYS:
                    result.files[key] = _load_file(cur, manifest, contract.files[key], ingested_at, scope)
            conn.commit()
            with conn.cursor() as cur:
                cur.execute("select ops.analyze_raw()")
            conn.commit()
        _record_attempt_end(attempt_id, manifest, "loaded")
        log.info("loaded batch %s: %s", manifest.batch_id, result.summary()["files"])
        return result
    except ContractError as exc:
        _record_attempt_end(attempt_id, manifest, "rejected", exc)
        raise
    except Exception as exc:
        _record_attempt_end(attempt_id, manifest, "failed", exc)
        raise
