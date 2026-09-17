"""Environment-backed configuration. No credential ever lives in code or Git (NFR-11)."""

from __future__ import annotations

import os
import re
import shutil
import sys
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

from cohortwarehouse.errors import ConfigurationError

STAGE_ROLES = ("admin", "loader", "transformer", "publisher", "bi_reader", "omop_reader")


def repo_root() -> Path:
    override = os.environ.get("CW_REPO_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parent.parent


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env reader: KEY=VALUE lines; existing environment variables win."""
    path = path or repo_root() / ".env"
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if re.fullmatch(r"[A-Z_][A-Z0-9_]*", key):
            os.environ.setdefault(key, value)


@dataclass(frozen=True)
class DatabaseTarget:
    host: str
    port: int
    dbname: str
    user: str
    password: str = ""

    def conninfo(self) -> dict[str, object]:
        return {
            "host": self.host,
            "port": self.port,
            "dbname": self.dbname,
            "user": self.user,
            "password": self.password,
            "application_name": "cohortwarehouse",
            "connect_timeout": 10,
        }

    def redacted(self) -> str:
        return f"postgresql://{self.user}:***@{self.host}:{self.port}/{self.dbname}"


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise ConfigurationError(f"environment variable {name} is required (see .env.example)")
    return value


def database_target(role: str) -> DatabaseTarget:
    if role not in STAGE_ROLES:
        raise ConfigurationError(f"unknown database role {role!r}")
    prefix = f"CW_{role.upper()}"
    password = os.environ.get(f"{prefix}_PASSWORD", "")
    if password == "CHANGE_ME":  # noqa: S105 - rejecting the .env.example placeholder, not a credential
        raise ConfigurationError(f"{prefix}_PASSWORD still has the placeholder value from .env.example")
    return DatabaseTarget(
        host=_env("CW_PG_HOST", "127.0.0.1"),
        port=int(_env("CW_PG_PORT", "5433")),
        dbname=_env("CW_PG_DATABASE", "cohortwarehouse"),
        user=_env(f"{prefix}_USER", f"cw_{role}"),
        password=password,
    )


@cache
def _yaml(relative: str) -> dict:
    path = repo_root() / relative
    if not path.is_file():
        raise ConfigurationError(f"missing configuration file {path}")
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def pipeline_config() -> dict:
    return _yaml("config/pipeline.yml")


def approved_generators() -> list[dict]:
    return _yaml("config/approved_generators.yml")["approved_generators"]


def validation_profile(name: str | None = None) -> tuple[str, dict]:
    name = name or os.environ.get("CW_VALIDATION_PROFILE", "fixture")
    profiles = pipeline_config()["validation_profiles"]
    if name not in profiles:
        raise ConfigurationError(f"unknown validation profile {name!r}; expected one of {sorted(profiles)}")
    return name, profiles[name]


def dbt_executable() -> str:
    """Configured dbt, else the dbt installed next to this interpreter (project venv), else `dbt` on PATH."""
    configured = os.environ.get("CW_DBT_EXECUTABLE", "dbt")
    if shutil.which(configured):
        return configured
    sibling = Path(sys.executable).parent / ("dbt.exe" if os.name == "nt" else "dbt")
    if sibling.exists():
        return str(sibling)
    raise ConfigurationError(f"dbt executable {configured!r} not found; set CW_DBT_EXECUTABLE")
