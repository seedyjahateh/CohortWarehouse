"""Reproducible Synthea generation (ING-01).

Runs the pinned Synthea jar with a fixed seed, location, population and end date, then writes a delivery
manifest recording the generator version, arguments, configuration hash, file hashes and record counts.
Requires Java 17+ and the jar referenced by config/demo.yml (downloaded separately; not vendored).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import shutil
import subprocess
from pathlib import Path

import yaml

from cohortwarehouse.contract import REQUIRED_FILE_KEYS, load_contract
from cohortwarehouse.errors import ConfigurationError
from cohortwarehouse.fingerprint import file_sha256
from cohortwarehouse.manifest import build_manifest, write_manifest
from cohortwarehouse.settings import repo_root

log = logging.getLogger(__name__)


def _config_hash(config: dict) -> str:
    # The runtime block (container vs host JDK) does not influence generated content, so it is not hashed.
    content = {k: v for k, v in config.items() if k != "runtime"}
    return hashlib.sha256(json.dumps(content, sort_keys=True, default=str).encode()).hexdigest()


def synthea_arguments(generator: dict, output_dir: Path) -> list[str]:
    # Both -r (reference date) and -e (end date) are pinned. Without -e Synthea simulates up to the wall
    # clock, so two runs with identical seeds differ: measured 2026-09-17, 87,484 vs 87,488 encounters and
    # 1,138,996 vs 1,139,160 observations. ING-01 requires reproducible clinical content.
    end_date = str(generator["simulation_end_date"]).replace("-", "")
    args = [
        "-s", str(generator["seed"]),
        "-cs", str(generator["clinician_seed"]),
        "-p", str(generator["requested_population"]),
        "-r", end_date,
        "-e", end_date,
    ]
    for key, value in sorted(generator["properties"].items()):
        args.append(f"--{key}={str(value).format(output_dir=output_dir.as_posix())}")
    args.append(generator["location"])
    return args


def generate(config_path: str, *, batch_id: str | None = None, delivered_at: str | None = None) -> dict:
    root = repo_root()
    config = yaml.safe_load((root / config_path).read_text(encoding="utf-8"))
    generator = config["generator"]
    jar = root / generator["jar_path"]
    if not jar.is_file():
        raise ConfigurationError(f"Synthea jar not found at {jar}; download the pinned release (see {config_path})")
    if generator.get("jar_sha256") and file_sha256(jar) != generator["jar_sha256"]:
        raise ConfigurationError("Synthea jar checksum does not match the pinned value")
    runtime = generator.get("runtime") or {"mode": "host"}

    end_date = str(generator["simulation_end_date"])
    batch_id = batch_id or f"{config['dataset_id']}-{end_date}-s{generator['seed']}"
    delivery_dir = root / config["output_root"] / batch_id
    work_dir = delivery_dir / "_synthea_output"
    if delivery_dir.exists():
        raise ConfigurationError(f"{delivery_dir} already exists; batch directories are immutable")
    work_dir.mkdir(parents=True)

    heap = f"-Xmx{runtime.get('max_heap', '3g')}"
    if runtime["mode"] == "docker":
        docker = shutil.which("docker")
        if not docker:
            raise ConfigurationError("runtime.mode is docker but docker is not on PATH")
        # Arguments are recorded with the container-internal output path so they are host independent.
        args = synthea_arguments(generator, Path("/output"))
        command = [
            docker, "run", "--rm", "--memory", runtime.get("container_memory", "4g"),
            "-v", f"{jar.parent.resolve()}:/tools:ro", "-v", f"{work_dir.resolve()}:/output",
            "-w", "/output", runtime["image"], "java", heap, "-jar", f"/tools/{jar.name}", *args,
        ]
    elif runtime["mode"] == "host":
        java = shutil.which("java")
        if not java:
            raise ConfigurationError("java is not on PATH (Synthea needs Java 17+); or set runtime.mode: docker")
        args = synthea_arguments(generator, work_dir)
        command = [java, heap, "-jar", str(jar), *args]
    else:
        raise ConfigurationError(f"unknown Synthea runtime mode {runtime['mode']!r}")

    log.info("running Synthea %s: %s", generator["version"], " ".join(args))
    completed = subprocess.run(command, cwd=work_dir, capture_output=True, text=True, check=False)
    (delivery_dir / "synthea_stdout.log").write_text(completed.stdout + completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise ConfigurationError(f"Synthea exited with {completed.returncode}; see synthea_stdout.log")

    csv_dir = work_dir / "csv"
    contract = load_contract()
    for key in REQUIRED_FILE_KEYS:
        shutil.move(str(csv_dir / contract.files[key].filename), delivery_dir / contract.files[key].filename)
    for extra in csv_dir.glob("*.csv"):  # out-of-scope files stay alongside for source accounting
        shutil.move(str(extra), delivery_dir / extra.name)
    shutil.rmtree(work_dir)

    document = build_manifest(
        delivery_dir,
        dataset_id=config["dataset_id"],
        batch_id=batch_id,
        source_revision=int(config["delivery"]["source_revision"]),
        as_of_date=end_date,
        delivered_at=delivered_at or dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        delivery_kind=config["delivery"]["kind"],
        replacement_mode=config["delivery"]["replacement_mode"],
        generator={
            "name": generator["name"],
            "version": generator["version"],
            "seed": int(generator["seed"]),
            "clinician_seed": int(generator["clinician_seed"]),
            "arguments": args,
            "config_sha256": _config_hash(generator),
            "simulation_end_date": end_date,
            "requested_population": int(generator["requested_population"]),
            "location": generator["location"],
        },
        notes="Generated by `python -m cohortwarehouse generate`. Actual patient count may differ from requested.",
    )
    manifest_path = write_manifest(delivery_dir, document)
    return {"manifest": str(manifest_path), "batch_id": batch_id,
            "records": {k: v["records"] for k, v in document["files"].items()}}
