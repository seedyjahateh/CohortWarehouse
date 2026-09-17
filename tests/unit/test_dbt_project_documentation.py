"""DOC gate without a database: every model file is documented with a description, grain and owner, and every
published model has at least one test (Section 7 DOC-01..04, Section 14 documentation metric)."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "dbt" / "models"


def _yaml_models() -> dict[str, dict]:
    documented = {}
    for path in MODELS.rglob("*.yml"):
        content = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for model in content.get("models", []):
            documented[model["name"]] = model
    return documented


def _has_tests(model: dict) -> bool:
    if model.get("data_tests"):
        return True
    return any(column.get("data_tests") for column in model.get("columns", []))


def test_every_model_is_documented_with_grain_and_owner():
    documented = _yaml_models()
    sql_models = {p.stem for p in MODELS.rglob("*.sql")}
    missing = sorted(sql_models - documented.keys())
    assert not missing, f"models without YAML documentation: {missing}"
    for name in sql_models:
        model = documented[name]
        meta = (model.get("config") or {}).get("meta") or {}
        assert model.get("description"), f"{name} lacks a description"
        assert meta.get("grain"), f"{name} lacks meta.grain"
        assert meta.get("owner"), f"{name} lacks meta.owner"


def test_every_published_mart_model_has_tests():
    documented = _yaml_models()
    published = {p.stem for p in (MODELS / "marts").rglob("*.sql")}
    # Evidence/profile tables are covered by singular tests (bi_member_evidence via cohort tests).
    exempt = {"bi_member_evidence", "bi_data_profile", "cw_exclusion_ledger"}
    untested = sorted(m for m in published - exempt if not _has_tests(documented[m]))
    assert not untested, f"published models without tests: {untested}"


def test_power_bi_exposure_covers_every_bi_model():
    exposures = yaml.safe_load((MODELS / "exposures.yml").read_text(encoding="utf-8"))["exposures"]
    report = next(e for e in exposures if e["name"] == "cohort_discovery_report")
    referenced = {d.split("'")[1] for d in report["depends_on"]}
    bi_models = {p.stem for p in (MODELS / "marts" / "bi").glob("*.sql")}
    assert bi_models == referenced
