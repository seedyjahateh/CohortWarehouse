"""Delivery manifests: schema validation, provenance gate, preflight, and manifest creation."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import jsonschema

from cohortwarehouse.contract import REQUIRED_FILE_KEYS, SourceContract, load_contract
from cohortwarehouse.errors import ContractError, ProvenanceError
from cohortwarehouse.fingerprint import file_sha256
from cohortwarehouse.settings import approved_generators, repo_root

MANIFEST_FILENAME = "manifest.json"


@dataclass(frozen=True)
class Manifest:
    path: Path
    document: dict
    sha256: str

    @property
    def batch_dir(self) -> Path:
        return self.path.parent

    @property
    def dataset_id(self) -> str:
        return self.document["dataset_id"]

    @property
    def batch_id(self) -> str:
        return self.document["batch_id"]

    @property
    def source_revision(self) -> int:
        return self.document["source_revision"]

    @property
    def replacement_mode(self) -> str:
        return self.document["replacement_mode"]

    @property
    def files(self) -> dict[str, dict]:
        return self.document["files"]

    @property
    def as_of(self) -> dt.date:
        return dt.date.fromisoformat(self.document["as_of_date"])

    @property
    def delivered(self) -> dt.datetime:
        return dt.datetime.fromisoformat(self.document["delivered_at"].replace("Z", "+00:00"))

    @property
    def patient_scope(self) -> list[str]:
        return list(self.document.get("patient_scope", []))

    @property
    def expected_quarantine(self) -> list[dict]:
        return list(self.document.get("expected_quarantine", []))


def _schema() -> dict:
    return json.loads((repo_root() / "config" / "manifest.schema.json").read_text(encoding="utf-8"))


def validate_document(document: dict) -> None:
    validator = jsonschema.Draft202012Validator(_schema(), format_checker=jsonschema.FormatChecker())
    errors = sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path))
    if errors:
        details = "; ".join(f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in errors[:10])
        raise ContractError(f"manifest failed schema validation: {details}")


def check_provenance(document: dict) -> None:
    """ING-07. A declaration, not a PHI detector: it only proves the workflow contract was followed."""
    if document.get("synthetic") is not True:
        raise ProvenanceError("manifest does not declare synthetic=true; refusing to load")
    generator = document.get("generator") or {}
    for approved in approved_generators():
        if generator.get("name") == approved["name"] and generator.get("version") in approved["versions"]:
            return
    raise ProvenanceError(
        f"generator {generator.get('name')!r} version {generator.get('version')!r} is not an approved "
        "synthetic generator (config/approved_generators.yml)"
    )


def load_manifest(path: str | Path, contract: SourceContract | None = None) -> Manifest:
    path = Path(path)
    if path.is_dir():
        path = path / MANIFEST_FILENAME
    if not path.is_file():
        raise ContractError(f"manifest not found: {path}")
    raw = path.read_bytes()
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"manifest is not valid UTF-8 JSON: {exc}") from None
    if not isinstance(document, dict):
        raise ContractError("manifest must be a JSON object")
    # Provenance first: a non-synthetic delivery is refused with that reason, whatever else is wrong with it.
    check_provenance(document)
    validate_document(document)
    contract = contract or load_contract()
    if document["source_contract_version"] != contract.version:
        raise ContractError(
            f"manifest targets contract {document['source_contract_version']!r}; "
            f"this code implements {contract.version!r}"
        )
    return Manifest(path=path, document=document, sha256=hashlib.sha256(raw).hexdigest())


def preflight(manifest: Manifest, contract: SourceContract | None = None) -> dict[str, list[str]]:
    """ING-02: every required file present, named per contract and matching its declared hash.

    Returns scope-accounting information about other files in the batch directory.
    """
    contract = contract or load_contract()
    problems: list[str] = []
    for key in REQUIRED_FILE_KEYS:
        declared = manifest.files[key]
        expected_name = contract.files[key].filename
        if declared["filename"] != expected_name:
            problems.append(f"{key}: manifest filename {declared['filename']!r} != contract {expected_name!r}")
            continue
        file_path = manifest.batch_dir / expected_name
        if not file_path.is_file():
            problems.append(f"{key}: required file {expected_name} is missing")
            continue
        actual = file_sha256(file_path)
        if actual != declared["sha256"]:
            problems.append(f"{key}: sha256 mismatch (manifest {declared['sha256'][:12]}..., file {actual[:12]}...)")
    if problems:
        raise ContractError("preflight failed: " + "; ".join(problems))

    required_names = {contract.files[k].filename for k in REQUIRED_FILE_KEYS}
    present = sorted(p.name for p in manifest.batch_dir.glob("*.csv"))
    return {
        "scope_excluded_files": [n for n in present if n in contract.excluded_files],
        "unknown_files": [n for n in present if n not in required_names and n not in contract.excluded_files],
    }


def count_csv_records(path: Path) -> int:
    """Parsed CSV records (not physical lines: quoted fields may contain newlines)."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        return sum(1 for _ in reader)


def build_manifest(
    batch_dir: str | Path,
    *,
    dataset_id: str,
    batch_id: str,
    source_revision: int,
    as_of_date: str,
    delivered_at: str,
    generator: dict,
    replacement_mode: str = "full",
    patient_scope: list[str] | None = None,
    delivery_kind: str = "manual",
    expected_quarantine: list[dict] | None = None,
    notes: str | None = None,
    contract: SourceContract | None = None,
) -> dict:
    contract = contract or load_contract()
    batch_dir = Path(batch_dir)
    files = {}
    for key in REQUIRED_FILE_KEYS:
        path = batch_dir / contract.files[key].filename
        if not path.is_file():
            raise ContractError(f"cannot build manifest: {path} is missing")
        files[key] = {
            "filename": path.name,
            "sha256": file_sha256(path),
            "records": count_csv_records(path),
        }
    document: dict = {
        "manifest_version": 1,
        "dataset_id": dataset_id,
        "batch_id": batch_id,
        "source_revision": source_revision,
        "as_of_date": as_of_date,
        "delivered_at": delivered_at,
        "delivery_kind": delivery_kind,
        "replacement_mode": replacement_mode,
        "synthetic": True,
        "generator": generator,
        "source_contract_version": contract.version,
        "files": files,
    }
    if replacement_mode == "scoped":
        document["patient_scope"] = sorted(patient_scope or [])
    if expected_quarantine:
        document["expected_quarantine"] = expected_quarantine
    if notes:
        document["notes"] = notes
    validate_document(document)
    return document


def write_manifest(batch_dir: str | Path, document: dict) -> Path:
    path = Path(batch_dir) / MANIFEST_FILENAME
    path.write_text(json.dumps(document, indent=2, sort_keys=False) + "\n", encoding="utf-8", newline="\n")
    return path
