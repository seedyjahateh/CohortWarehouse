from __future__ import annotations

import hashlib
import os
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cohortwarehouse.settings import load_dotenv  # noqa: E402

load_dotenv()

FIXTURE = ROOT / "tests" / "fixtures" / "synthetic_25"
VOCABULARY = ROOT / "tests" / "fixtures" / "vocabulary"


def patient_uuid(number: int) -> str:
    return f"00000000-0000-4000-8000-{number:012d}"


def pseudo_id(number: int, dataset: str = "fixture") -> str:
    """Independent re-implementation of the dbt `pseudonym` macro."""
    return hashlib.sha256(f"{dataset}:{patient_uuid(number)}".encode()).hexdigest()[:20]


@pytest.fixture(scope="session")
def expected() -> dict:
    return yaml.safe_load((FIXTURE / "expected.yml").read_text(encoding="utf-8"))


@pytest.fixture
def batch_copy(tmp_path):
    """Copy a fixture batch to a temp dir so a test can mutate it."""

    def _copy(name: str = "batch_A") -> Path:
        target = tmp_path / name
        shutil.copytree(FIXTURE / name, target)
        return target

    return _copy


def _database_reachable() -> tuple[bool, str]:
    try:
        from cohortwarehouse.db import connect

        with connect("admin") as conn, conn.cursor() as cur:
            cur.execute("select 1")
        return True, ""
    except Exception as exc:  # pragma: no cover - environment dependent
        return False, f"{type(exc).__name__}: {exc}"


@pytest.fixture(scope="session")
def database():
    ok, reason = _database_reachable()
    if not ok:
        pytest.skip(f"PostgreSQL not reachable ({reason}); start it with `docker compose up -d warehouse`")
    return True


@pytest.fixture(scope="session")
def disposable_database(database):
    """Tests that rebuild candidate schemas and publish releases need a database they may wipe."""
    if os.environ.get("CW_TEST_DISPOSABLE_DB") != "1":
        pytest.skip("set CW_TEST_DISPOSABLE_DB=1 to allow the lifecycle tests to wipe and rebuild the warehouse")
    return True
