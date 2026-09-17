"""Thin, logged wrapper around the dbt CLI. dbt runs as a subprocess so it can live in its own venv.

Run context (run id, git sha, failure injection) is passed through environment variables rather than
--vars, and the target path is stable, so dbt's partial parsing survives between runs. Each
invocation's artifacts are copied to dbt/target/runs/<run_id>/<label>/ for evidence.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from cohortwarehouse.errors import BuildError, QualityGateError, TransientError
from cohortwarehouse.settings import dbt_executable, repo_root

log = logging.getLogger(__name__)

# Stages mirror the Airflow DAG (Section 9.3). `cautious` indirect selection means a test runs in a
# stage only when all of its parents were built in that stage; the quality gate reruns every test.
STAGES: dict[str, list[str]] = {
    "staging_intermediate": ["resource_type:seed", "path:models/staging", "path:models/intermediate"],
    "star_omop": ["path:models/marts/star", "path:models/marts/omop"],
    "bi": ["path:models/marts/bi"],
}
ARTIFACTS = ("run_results.json", "manifest.json", "catalog.json", "sources.json", "index.html")


@dataclass
class DbtResult:
    command: str
    returncode: int
    seconds: float
    artifacts_path: Path
    results: list[dict] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self.results:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        return counts

    def failures(self) -> list[dict]:
        return [
            {"unique_id": r["unique_id"], "status": r["status"], "message": (r.get("message") or "")[:500],
             "failures": r.get("failures")}
            for r in self.results
            if r["status"] in {"error", "fail", "runtime error", "skipped"}
        ]

    def tests(self) -> list[dict]:
        return [r for r in self.results if r["unique_id"].startswith("test.")]


def dbt_dir() -> Path:
    return repo_root() / "dbt"


def run_dbt(
    command: str,
    *,
    run_id: str,
    label: str,
    select: list[str] | None = None,
    full_refresh: bool = False,
    git_sha: str = "unknown",
    extra_args: list[str] | None = None,
    raise_on_failure: bool = True,
) -> DbtResult:
    project = dbt_dir()
    target_path = project / "target"
    artifacts_path = target_path / "runs" / run_id / label
    args = [
        dbt_executable(), *command.split(),  # e.g. "build" or "docs generate"
        "--project-dir", str(project),
        "--profiles-dir", str(project),
        "--target-path", str(target_path),
        "--log-path", str(project / "logs"),
        "--no-use-colors",
    ]
    if select:
        args += ["--select", *select, "--indirect-selection", "cautious"]
    if full_refresh and command in {"build", "run", "seed"}:
        args.append("--full-refresh")
    args += extra_args or []

    env = dict(os.environ)
    env["CW_RUN_ID"] = run_id
    env["CW_GIT_SHA"] = git_sha
    env.setdefault("DBT_SEND_ANONYMOUS_USAGE_STATS", "false")
    (target_path / "run_results.json").unlink(missing_ok=True)

    log.info("dbt %s [%s]%s", command, label, " --full-refresh" if full_refresh else "")
    started = time.perf_counter()
    completed = subprocess.run(args, cwd=project, env=env, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", check=False)
    seconds = time.perf_counter() - started

    artifacts_path.mkdir(parents=True, exist_ok=True)
    (artifacts_path / "dbt_stdout.log").write_text(completed.stdout + completed.stderr, encoding="utf-8")
    for name in ARTIFACTS:
        if (target_path / name).is_file():
            shutil.copy2(target_path / name, artifacts_path / name)

    result = DbtResult(command, completed.returncode, round(seconds, 3), artifacts_path)
    run_results = artifacts_path / "run_results.json"
    if run_results.is_file():
        result.results = json.loads(run_results.read_text(encoding="utf-8")).get("results", [])
    log.info("dbt %s [%s] finished in %.1fs rc=%s %s", command, label, seconds, completed.returncode, result.counts)

    if completed.returncode != 0 and raise_on_failure:
        tail = "\n".join((completed.stdout + completed.stderr).strip().splitlines()[-25:])
        if not result.results:
            if "connection" in tail.lower() and ("refused" in tail.lower() or "timeout" in tail.lower()):
                raise TransientError(f"dbt {command} [{label}] could not connect:\n{tail}")
            raise BuildError(f"dbt {command} [{label}] failed before executing nodes:\n{tail}")
        failures = result.failures()
        only_tests = all(f["unique_id"].startswith("test.") for f in failures if f["status"] != "skipped")
        error_class = QualityGateError if only_tests else BuildError
        raise error_class(
            f"dbt {command} [{label}] failed: {len(failures)} failing/skipped nodes; "
            f"first: {json.dumps(failures[:3], default=str)}\nlog: {artifacts_path / 'dbt_stdout.log'}"
        )
    return result
