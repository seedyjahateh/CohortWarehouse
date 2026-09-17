"""Derive a scoped delivery that changes a fixed share of people from a full Synthea delivery (NFR-02).

    python scripts/make_incremental_delivery.py \
        --source data/deliveries/synthea_demo/synthea_demo-2026-06-30-s20260915 \
        --batch-id synthea_demo-2026-06-30-incr5 --revision 2 --delivered-at 2026-07-02T04:30:00Z

Changed people are chosen deterministically (SHA-256 of seed + patient id) and split across change kinds so the
incremental benchmark exercises every path the PRD names:

* late_arrival   (40%) - a new encounter dated before the person's latest event, with a systolic reading
* correction     (30%) - one numeric observation value changes (a keyless correction: old identity removed)
* events_removed (20%) - patient row kept, every event removed (scoped replacement)
* person_removed (10%) - patient absent from the scoped batch
* new_person     (+ a further 0.5% of the population) - clones of unchosen people with fresh UUIDs

The derivation is recorded as its own approved generator so provenance stays honest: it is synthetic data
derived from a synthetic Synthea delivery, not a new Synthea run.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cohortwarehouse.manifest import build_manifest, load_manifest, write_manifest  # noqa: E402

EVENT_FILES = ("encounters", "conditions", "medications", "observations")
PATIENT_COLUMN = {"encounters": "PATIENT", "conditions": "PATIENT", "medications": "PATIENT", "observations": "PATIENT"}


def _rank(seed: str, value: str) -> str:
    return hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()


def _read(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        yield header
        yield from reader


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--revision", required=True, type=int)
    parser.add_argument("--delivered-at", required=True)
    parser.add_argument("--fraction", type=float, default=0.05)
    parser.add_argument("--seed", default="nfr02-v1")
    parser.add_argument("--output-root", type=Path, default=None)
    args = parser.parse_args(argv)

    source = load_manifest(args.source / "manifest.json")
    output = (args.output_root or args.source.parent) / args.batch_id
    if output.exists():
        raise SystemExit(f"{output} exists; deliveries are immutable")
    output.mkdir(parents=True)

    patients = list(_read(args.source / "patients.csv"))
    p_header, p_rows = patients[0], patients[1:]
    ids = sorted((row[p_header.index("Id")] for row in p_rows), key=lambda i: _rank(args.seed, i))
    changed_count = max(1, round(len(ids) * args.fraction))
    chosen = ids[:changed_count]
    kinds: dict[str, str] = {}
    for position, patient_id in enumerate(chosen):
        share = position / changed_count
        kinds[patient_id] = ("late_arrival" if share < 0.4 else "correction" if share < 0.7
                             else "events_removed" if share < 0.9 else "person_removed")
    clone_sources = ids[changed_count:changed_count + max(1, round(len(ids) * 0.005))]
    clone_ids = {src: str(uuid.UUID(_rank(args.seed + ":clone", src)[:32], version=4)) for src in clone_sources}
    scope = set(chosen) | set(clone_ids.values())

    # ---- patients: kept people (not person_removed) + clones
    with (output / "patients.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(p_header)
        id_col = p_header.index("Id")
        for row in p_rows:
            if kinds.get(row[id_col]) and kinds[row[id_col]] != "person_removed":
                writer.writerow(row)
            if row[id_col] in clone_ids:
                writer.writerow([clone_ids[row[id_col]] if i == id_col else v for i, v in enumerate(row)])

    # ---- encounters first (clones need remapped encounter ids; late arrivals need a template encounter)
    encounter_map: dict[str, str] = {}
    latest_encounter: dict[str, list[str]] = {}
    counts = {k: 0 for k in ("late_arrival", "correction", "events_removed", "person_removed", "new_person")}
    corrected: set[str] = set()
    for file_key in EVENT_FILES:
        rows = _read(args.source / f"{file_key}.csv")
        header = next(rows)
        patient_col = header.index(PATIENT_COLUMN[file_key])
        with (output / f"{file_key}.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(header)
            for row in rows:
                patient_id = row[patient_col]
                kind = kinds.get(patient_id)
                if kind in {"late_arrival", "correction"}:
                    if file_key == "encounters":
                        start = row[header.index("START")]
                        if patient_id not in latest_encounter or start > latest_encounter[patient_id][1]:
                            latest_encounter[patient_id] = [row, start]
                    if (kind == "correction" and file_key == "observations" and patient_id not in corrected
                            and row[header.index("TYPE")] == "numeric"):
                        value = row[header.index("VALUE")]
                        try:
                            row = list(row)
                            row[header.index("VALUE")] = f"{float(value) + 1:.1f}"
                            corrected.add(patient_id)
                        except ValueError:
                            pass
                    writer.writerow(row)
                if patient_id in clone_ids:
                    clone = list(row)
                    clone[patient_col] = clone_ids[patient_id]
                    if file_key == "encounters":
                        new_id = str(uuid.UUID(_rank(args.seed + ":enc", row[0])[:32], version=4))
                        encounter_map[row[0]] = new_id
                        clone[0] = new_id
                    elif "ENCOUNTER" in header and clone[header.index("ENCOUNTER")]:
                        clone[header.index("ENCOUNTER")] = encounter_map.get(clone[header.index("ENCOUNTER")], "")
                    writer.writerow(clone)
            if file_key == "encounters":
                for patient_id, (template, start) in latest_encounter.items():
                    if kinds[patient_id] != "late_arrival":
                        continue
                    late = list(template)
                    late_start = dt.datetime.fromisoformat(start.replace("Z", "+00:00")) - dt.timedelta(days=45)
                    late[0] = str(uuid.UUID(_rank(args.seed + ":late", patient_id)[:32], version=4))
                    late[header.index("START")] = late_start.strftime("%Y-%m-%dT%H:%M:%SZ")
                    late[header.index("STOP")] = (late_start + dt.timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
                    writer.writerow(late)
            if file_key == "observations":
                for patient_id, (template, start) in latest_encounter.items():
                    if kinds[patient_id] != "late_arrival":
                        continue
                    late_start = dt.datetime.fromisoformat(start.replace("Z", "+00:00")) - dt.timedelta(days=45)
                    late_id = str(uuid.UUID(_rank(args.seed + ":late", patient_id)[:32], version=4))
                    writer.writerow([(late_start + dt.timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                     patient_id, late_id, "vital-signs", "8480-6", "Systolic Blood Pressure",
                                     "128.0", "mm[Hg]", "numeric"])

    for kind in kinds.values():
        counts[kind] += 1
    counts["new_person"] = len(clone_ids)
    shutil.copy2(args.source / "organizations.csv", output / "organizations.csv")

    generator = {
        "name": "cohortwarehouse-incremental-derivation",
        "version": "1",
        "seed": int(_rank(args.seed, "seed")[:8], 16),
        "arguments": [f"--source-batch={source.batch_id}", f"--fraction={args.fraction}", f"--seed={args.seed}"],
        "config_sha256": hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
        "simulation_end_date": source.document["generator"]["simulation_end_date"],
    }
    document = build_manifest(
        output, dataset_id=source.dataset_id, batch_id=args.batch_id, source_revision=args.revision,
        as_of_date=source.document["as_of_date"], delivered_at=args.delivered_at, generator=generator,
        replacement_mode="scoped", patient_scope=sorted(scope), delivery_kind="manual",
        notes=f"NFR-02 derived scoped delivery from {source.batch_id}: {json.dumps(counts)}",
    )
    write_manifest(output, document)
    print(json.dumps({"manifest": str(output / "manifest.json"), "population": len(ids), "scope": len(scope),
                      "changes": counts, "records": {k: v["records"] for k, v in document["files"].items()}},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
