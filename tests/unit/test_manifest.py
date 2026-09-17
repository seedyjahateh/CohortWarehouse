import json

import pytest

from cohortwarehouse.errors import ContractError, ProvenanceError
from cohortwarehouse.manifest import load_manifest, preflight, validate_document
from tests.conftest import FIXTURE


@pytest.mark.parametrize("batch", ["batch_A", "batch_B", "batch_C"])
def test_committed_fixture_manifests_are_valid_and_hashes_match(batch):
    # Also guards .gitattributes: a line-ending rewrite on checkout would break these hashes.
    manifest = load_manifest(FIXTURE / batch / "manifest.json")
    accounting = preflight(manifest)
    assert accounting["unknown_files"] == []


def _document(batch="batch_A"):
    return json.loads((FIXTURE / batch / "manifest.json").read_text(encoding="utf-8"))


def _write(tmp_path, document):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_scoped_manifest_requires_scope():
    document = _document("batch_B")
    del document["patient_scope"]
    with pytest.raises(ContractError, match="patient_scope"):
        validate_document(document)


def test_full_manifest_rejects_scope():
    document = _document("batch_A")
    document["patient_scope"] = ["x"]
    with pytest.raises(ContractError):
        validate_document(document)


def test_non_synthetic_batch_is_rejected_before_anything_else(tmp_path):
    document = _document()
    document["synthetic"] = False
    with pytest.raises(ProvenanceError, match="synthetic"):
        load_manifest(_write(tmp_path, document))


def test_unapproved_generator_is_rejected(tmp_path):
    document = _document()
    document["generator"]["name"] = "hospital-ehr-export"
    with pytest.raises(ProvenanceError, match="not an approved"):
        load_manifest(_write(tmp_path, document))


def test_preflight_detects_missing_file_and_hash_mismatch(batch_copy):
    directory = batch_copy("batch_A")
    (directory / "medications.csv").unlink()
    with (directory / "conditions.csv").open("a", encoding="utf-8", newline="") as handle:
        handle.write("2026-01-01,,x,,,1,tampered\n")
    manifest = load_manifest(directory / "manifest.json")
    with pytest.raises(ContractError) as excinfo:
        preflight(manifest)
    assert "medications.csv is missing" in str(excinfo.value)
    assert "conditions: sha256 mismatch" in str(excinfo.value)


def test_contract_version_mismatch_is_rejected(tmp_path):
    document = _document()
    document["source_contract_version"] = "synthea-csv-0.9"
    with pytest.raises(ContractError, match="contract"):
        load_manifest(_write(tmp_path, document))
