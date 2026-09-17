"""Prerequisite and configuration checks (`python -m cohortwarehouse doctor`)."""

from __future__ import annotations

import os
import platform
import re
import subprocess
import sys

from cohortwarehouse.errors import CohortWarehouseError
from cohortwarehouse.settings import STAGE_ROLES, database_target, dbt_executable, repo_root


def _check(name: str, fn) -> dict:
    try:
        detail = fn()
        return {"check": name, "ok": True, "detail": detail}
    except CohortWarehouseError as exc:
        return {"check": name, "ok": False, "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001 - doctor reports, never crashes
        return {"check": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}"}


def _python():
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError(f"Python 3.12 required, found {platform.python_version()}")
    return platform.python_version()


def _dbt():
    out = subprocess.run([dbt_executable(), "--version"], capture_output=True, text=True, timeout=120, check=True)
    core = re.search(r"Core:\s*\n\s*-\s*installed:\s*([\d.]+)", out.stdout)
    postgres = re.search(r"-\s*postgres:\s*([\d.]+)", out.stdout)
    versions = {"core": core.group(1) if core else None, "postgres": postgres.group(1) if postgres else None}
    lock = (repo_root() / "requirements" / "dbt.lock").read_text(encoding="utf-8")
    for component, pin in (("core", "dbt-core"), ("postgres", "dbt-postgres")):
        pinned = re.search(rf"^{pin}==([\d.]+)$", lock, re.M).group(1)
        if versions.get(component) != pinned:
            raise RuntimeError(f"dbt-{component} {versions.get(component)} does not match lock {pinned}")
    return versions


def _env_file():
    if not (repo_root() / ".env").is_file() and "CW_ADMIN_PASSWORD" not in os.environ:
        raise RuntimeError("no .env file and no CW_* environment; copy .env.example to .env")
    placeholders = [k for k, v in os.environ.items() if k.startswith("CW_") and v == "CHANGE_ME"]
    if placeholders:
        raise RuntimeError(f"placeholder values still set: {sorted(placeholders)}")
    return "configured"


def _pinned_images():
    compose = (repo_root() / "compose.yml").read_text(encoding="utf-8")
    images = re.findall(r"image:\s*(\S+)", compose)
    floating = [i for i in images if "@sha256:" not in i and not i.startswith("cohortwarehouse-")]
    if floating:
        raise RuntimeError(f"images not pinned by digest: {floating}")
    return images


def _database():
    from cohortwarehouse.db import connect, fetch_all_dicts, fetch_one_dict

    results = {}
    for role in STAGE_ROLES:
        with connect(role) as conn:
            row = fetch_one_dict(conn, "select current_user as role, current_setting('server_version') as version")
            results[role] = row
    with connect("admin") as conn:
        migrations = fetch_all_dicts(conn, "select filename, applied_at from ops.schema_migration order by filename")
        vocab = fetch_one_dict(conn, "select vocabulary_version, is_test_only from ops.vocabulary_release "
                                     "where is_current")
        current = fetch_all_dicts(conn, "select dataset_id, release_id, switched_at from ops.current_release")
    return {"connections": results, "target": database_target("admin").redacted(), "migrations": migrations,
            "vocabulary": vocab, "current_releases": current}


def _official_ddl():
    from cohortwarehouse.omop_ddl import DDL_SOURCE, load_ddl

    return {"source": DDL_SOURCE, "tables": len(load_ddl())}


def _contract():
    from cohortwarehouse.contract import load_contract

    contract = load_contract()
    return {"version": contract.version, "files": sorted(contract.files)}


def run_doctor() -> dict:
    checks = [
        _check("python", _python),
        _check("environment", _env_file),
        _check("pinned_images", _pinned_images),
        _check("source_contract", _contract),
        _check("official_omop_ddl", _official_ddl),
        _check("dbt", _dbt),
        _check("database", _database),
    ]
    return {"ok": all(c["ok"] for c in checks), "platform": platform.platform(), "checks": checks}
