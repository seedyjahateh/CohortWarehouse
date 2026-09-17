"""Versioned source contract: header validation and required-type checks (ING-02, ING-03)."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import yaml

from cohortwarehouse.errors import ContractError
from cohortwarehouse.settings import repo_root

REQUIRED_FILE_KEYS = ("patients", "encounters", "conditions", "medications", "observations", "organizations")
VALID_TYPES = {"id", "date", "timestamp", "decimal", "text"}

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?)(Z|[+-]\d{2}:\d{2})$")
# PostgreSQL accepts far wider ranges; clinical data outside this window is a source defect.
_MIN_YEAR, _MAX_YEAR = 1850, 2200


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    header_required: bool
    nullable: bool
    load: bool

    @property
    def raw_name(self) -> str:
        return self.name.lower()


@dataclass(frozen=True)
class FileContract:
    key: str
    filename: str
    patient_column: str | None
    columns: tuple[Column, ...]

    @property
    def loaded_columns(self) -> tuple[Column, ...]:
        return tuple(c for c in self.columns if c.load)

    @property
    def known_names(self) -> frozenset[str]:
        return frozenset(c.name for c in self.columns)


@dataclass(frozen=True)
class SourceContract:
    version: str
    fingerprint_format: str
    files: dict[str, FileContract]
    excluded_files: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class HeaderCheck:
    positions: dict[str, int]          # loaded column name -> CSV position (absent optional: missing)
    extra_columns: list[str]
    missing_optional_columns: list[str]
    unloaded_present_columns: list[str]


def _parse_column(file_key: str, spec: dict) -> Column:
    try:
        name, ctype = spec["name"], spec["type"]
    except KeyError as exc:
        raise ContractError(f"contract column in {file_key} lacks {exc}") from None
    if ctype not in VALID_TYPES:
        raise ContractError(f"{file_key}.{name}: unknown type {ctype!r}")
    header = spec.get("header", "required")
    if header not in {"required", "optional"}:
        raise ContractError(f"{file_key}.{name}: header must be required|optional")
    return Column(
        name=name,
        type=ctype,
        header_required=header == "required",
        nullable=bool(spec.get("nullable", True)),
        load=bool(spec.get("load", True)),
    )


def parse_contract(document: dict) -> SourceContract:
    files: dict[str, FileContract] = {}
    for key, spec in (document.get("files") or {}).items():
        columns = tuple(_parse_column(key, c) for c in spec["columns"])
        names = [c.name for c in columns]
        if len(names) != len(set(names)):
            raise ContractError(f"{key}: duplicate column names in contract")
        patient_column = spec.get("patient_column")
        if patient_column is not None and patient_column not in names:
            raise ContractError(f"{key}: patient_column {patient_column!r} is not a contract column")
        files[key] = FileContract(key, spec["filename"], patient_column, columns)
    missing = set(REQUIRED_FILE_KEYS) - set(files)
    if missing:
        raise ContractError(f"contract lacks required files: {sorted(missing)}")
    return SourceContract(
        version=document["contract_version"],
        fingerprint_format=document.get("row_fingerprint", "sha256-canonical-v1"),
        files=files,
        excluded_files=tuple(f["filename"] for f in document.get("excluded_files", [])),
    )


@cache
def load_contract(path: str | None = None) -> SourceContract:
    contract_path = Path(path) if path else repo_root() / "config" / "source_contract.yml"
    with contract_path.open(encoding="utf-8") as handle:
        return parse_contract(yaml.safe_load(handle))


def check_header(contract: FileContract, header: list[str]) -> HeaderCheck:
    """Fail on missing required or duplicated headers; record extras (ING-03)."""
    duplicates = sorted({h for h in header if header.count(h) > 1})
    if duplicates:
        raise ContractError(f"{contract.filename}: duplicate header columns {duplicates}")
    present = {name: i for i, name in enumerate(header)}
    missing_required = [c.name for c in contract.columns if c.header_required and c.name not in present]
    if missing_required:
        raise ContractError(
            f"{contract.filename}: missing or renamed required columns {missing_required}"
        )
    return HeaderCheck(
        positions={c.name: present[c.name] for c in contract.loaded_columns if c.name in present},
        extra_columns=[h for h in header if h not in contract.known_names],
        missing_optional_columns=[
            c.name for c in contract.columns if not c.header_required and c.load and c.name not in present
        ],
        unloaded_present_columns=[c.name for c in contract.columns if not c.load and c.name in present],
    )


def _valid_date(value: str) -> bool:
    if not _DATE_RE.match(value):
        return False
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError:
        return False
    return _MIN_YEAR <= parsed.year <= _MAX_YEAR


def _valid_timestamp(value: str) -> bool:
    match = _TS_RE.match(value)
    if not match:
        return False
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return _MIN_YEAR <= parsed.year <= _MAX_YEAR


def validate_value(column: Column, value: str | None) -> str | None:
    """Return a quarantine reason, or None when the value satisfies the contract."""
    if value is None:
        return None if column.nullable else f"null_required:{column.name}"
    if column.type == "id" and not _ID_RE.match(value):
        return f"invalid_id:{column.name}"
    if column.type == "date" and not _valid_date(value):
        return f"invalid_date:{column.name}"
    if column.type == "timestamp" and not _valid_timestamp(value):
        return f"invalid_timestamp:{column.name}"
    return None
