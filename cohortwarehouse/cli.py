"""Operator CLI (PRD Section 12.3). Airflow tasks call the same functions this CLI calls."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from cohortwarehouse.errors import CohortWarehouseError
from cohortwarehouse.settings import load_dotenv

log = logging.getLogger("cohortwarehouse")


def _print(payload) -> None:
    print(json.dumps(payload, indent=2, default=str))


def cmd_doctor(args) -> int:
    from cohortwarehouse.doctor import run_doctor

    report = run_doctor()
    _print(report)
    return 0 if report["ok"] else 1


def cmd_bootstrap(args) -> int:
    from cohortwarehouse.bootstrap import bootstrap

    bootstrap(create_login_roles=not args.skip_login_roles)
    _print({"bootstrap": "ok"})
    return 0


def cmd_load_vocabulary(args) -> int:
    from cohortwarehouse.vocabulary import load_vocabulary

    _print(load_vocabulary(args.path, license_note=args.license_note))
    return 0


def cmd_generate(args) -> int:
    from cohortwarehouse.generate import generate

    _print(generate(args.config, batch_id=args.batch_id, delivered_at=args.delivered_at))
    return 0


def cmd_ingest(args) -> int:
    from cohortwarehouse.ingest import ingest

    _print(ingest(args.manifest).summary())
    return 0


def cmd_run(args) -> int:
    from cohortwarehouse.pipeline import run_pipeline

    result = run_pipeline(
        batch_id=args.batch_id,
        full_refresh=args.full_refresh,
        validation_only=args.validation_only,
        profile=args.profile,
        trigger="cli",
    )
    _print(result)
    return 0


def cmd_validate(args) -> int:
    from cohortwarehouse.publish import validate_release

    report = validate_release(args.release)
    _print(report)
    return 0 if report["ok"] else 4


def cmd_publish(args) -> int:
    from cohortwarehouse.publish import publish

    _print(publish(args.validated_run))
    return 0


def cmd_restore(args) -> int:
    from cohortwarehouse.publish import restore

    _print(restore(args.release, dataset_id=args.dataset_id, reason=args.reason))
    return 0


def cmd_releases(args) -> int:
    from cohortwarehouse.publish import list_releases

    _print(list_releases(args.dataset_id))
    return 0


def cmd_pin(args) -> int:
    from cohortwarehouse.publish import pin_release

    _print(pin_release(args.release, args.report, unpin=args.unpin))
    return 0


def cmd_cleanup(args) -> int:
    from cohortwarehouse.retention import cleanup

    _print(cleanup(dataset_id=args.dataset_id, apply=args.apply))
    return 0


def cmd_benchmark(args) -> int:
    from cohortwarehouse.benchmark import benchmark

    _print(benchmark(profile=args.profile, runs=args.runs, manifest=args.manifest))
    return 0


def cmd_freshness(args) -> int:
    from cohortwarehouse.freshness import check_freshness

    report = check_freshness(args.dataset_id, mode=args.mode)
    _print(report)
    return 0 if report["status"] != "fail" else 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m cohortwarehouse", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="check prerequisites, connectivity, pinned versions").set_defaults(func=cmd_doctor)

    p = sub.add_parser("bootstrap", help="create roles, schemas, ops/raw tables, CDM DDL, grants (idempotent)")
    p.add_argument("--skip-login-roles", action="store_true")
    p.set_defaults(func=cmd_bootstrap)

    p = sub.add_parser("load-vocabulary", help="load an Athena-format vocabulary directory into vocab")
    p.add_argument("path")
    p.add_argument("--license-note", required=True, help="how access/licences were obtained (GOV-03)")
    p.set_defaults(func=cmd_load_vocabulary)

    p = sub.add_parser("generate", help="run pinned Synthea and write a delivery manifest")
    p.add_argument("--config", default="config/demo.yml")
    p.add_argument("--batch-id")
    p.add_argument("--delivered-at")
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("ingest", help="validate a manifest and load its batch transactionally")
    p.add_argument("--manifest", required=True)
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("run", help="build candidates for a loaded batch and run the quality gate")
    p.add_argument("--batch-id", required=True)
    p.add_argument("--full-refresh", action="store_true")
    p.add_argument("--validation-only", action="store_true", help="historical build for inspection only")
    p.add_argument("--profile", choices=["fixture", "release"], default=None)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("validate", help="re-verify a published release against its recorded checksums")
    p.add_argument("--release", required=True)
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("publish", help="atomically publish a validated run as an immutable release")
    p.add_argument("--validated-run", required=True)
    p.set_defaults(func=cmd_publish)

    p = sub.add_parser("restore", help="atomically point stable views back at a retained release")
    p.add_argument("--release", required=True)
    p.add_argument("--dataset-id", default=None)
    p.add_argument("--reason", default="operator restore")
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser("releases", help="list releases and the current pointer")
    p.add_argument("--dataset-id", default=None)
    p.set_defaults(func=cmd_releases)

    p = sub.add_parser("pin", help="pin a release used by a Power BI report so cleanup keeps it")
    p.add_argument("--release", required=True)
    p.add_argument("--report", required=True)
    p.add_argument("--unpin", action="store_true")
    p.set_defaults(func=cmd_pin)

    p = sub.add_parser("cleanup", help="apply retention policy (dry run unless --apply)")
    p.add_argument("--dataset-id", required=True)
    group = p.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", default=True)
    group.add_argument("--apply", action="store_true")
    p.set_defaults(func=cmd_cleanup)

    p = sub.add_parser("benchmark", help="timed end-to-end runs with stage breakdown")
    p.add_argument("--profile", default="demo")
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--manifest", default=None)
    p.set_defaults(func=cmd_benchmark)

    p = sub.add_parser("freshness", help="delivery freshness (independent of clinical event dates)")
    p.add_argument("--dataset-id", required=True)
    p.add_argument("--mode", choices=["scheduled", "frozen_demo"], default=None)
    p.set_defaults(func=cmd_freshness)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    try:
        return args.func(args)
    except CohortWarehouseError as exc:
        log.error("%s: %s", type(exc).__name__, exc)
        return exc.exit_code
