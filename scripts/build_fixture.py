"""Build the 25-person development fixture, its three ordered batches, and the fictional vocabulary.

    python scripts/build_fixture.py            # (re)writes tests/fixtures/synthetic_25 and tests/fixtures/vocabulary

Every person exists to exercise one or more boundary cases from PRD Section 11.3; the case is
written next to the person. Expected cohort memberships are NOT computed here: they are written
by hand in tests/fixtures/synthetic_25/expected.yml so the pipeline is checked against an
independent statement of intent.

Output is byte-deterministic (UTF-8, LF, stable ordering) so manifest hashes are reproducible.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import random
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cohortwarehouse.manifest import build_manifest, write_manifest  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "synthetic_25"
VOCAB = ROOT / "tests" / "fixtures" / "vocabulary"
DATASET = "fixture"
AS_OF = "2026-06-30"

PATIENT_HEADER = [
    "Id", "BIRTHDATE", "DEATHDATE", "SSN", "DRIVERS", "PASSPORT", "PREFIX", "FIRST", "MIDDLE", "LAST", "SUFFIX",
    "MAIDEN", "MARITAL", "RACE", "ETHNICITY", "GENDER", "BIRTHPLACE", "ADDRESS", "CITY", "STATE", "COUNTY", "FIPS",
    "ZIP", "LAT", "LON", "HEALTHCARE_EXPENSES", "HEALTHCARE_COVERAGE", "INCOME",
]
ENCOUNTER_HEADER = [
    "Id", "START", "STOP", "PATIENT", "ORGANIZATION", "PROVIDER", "PAYER", "ENCOUNTERCLASS", "CODE", "DESCRIPTION",
    "BASE_ENCOUNTER_COST", "TOTAL_CLAIM_COST", "PAYER_COVERAGE", "REASONCODE", "REASONDESCRIPTION",
]
CONDITION_HEADER = ["START", "STOP", "PATIENT", "ENCOUNTER", "SYSTEM", "CODE", "DESCRIPTION"]
MEDICATION_HEADER = [
    "START", "STOP", "PATIENT", "PAYER", "ENCOUNTER", "CODE", "DESCRIPTION", "BASE_COST", "PAYER_COVERAGE",
    "DISPENSES", "TOTALCOST", "REASONCODE", "REASONDESCRIPTION",
]
OBSERVATION_HEADER = ["DATE", "PATIENT", "ENCOUNTER", "CATEGORY", "CODE", "DESCRIPTION", "VALUE", "UNITS", "TYPE"]
# FIXTURE_EXTRA is deliberately unknown to the contract: it must be recorded and ignored.
ORGANIZATION_HEADER = ["Id", "NAME", "ADDRESS", "CITY", "STATE", "ZIP", "LAT", "LON", "PHONE", "REVENUE",
                       "UTILIZATION", "FIXTURE_EXTRA"]

SNOMED_URI = "http://snomed.info/sct"
ORG1 = "10000000-0000-4000-8000-000000000001"
ORG2 = "10000000-0000-4000-8000-000000000002"


def pid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


def eid(n: int, k: int) -> str:
    return f"e{n:07d}-0000-4000-8000-{k:012d}"


HTN_E = ("59621000", "Essential hypertension (disorder)")
HTN_S = ("38341003", "Hypertensive disorder, systemic arterial (disorder)")
T2DM = ("44054006", "Diabetes mellitus type 2 (disorder)")
PREDIAB = ("15777000", "Prediabetes (finding)")
EMPLOY = ("160903007", "Full-time employment (finding)")            # maps to Observation domain
NEURO = ("368581000119106", "Neuropathy due to type 2 diabetes mellitus (disorder)")  # one-to-many
VIOLENCE = ("424393004", "Reports of violence in the environment (finding)")  # Maps to + Maps to value
UNKNOWN_COND = ("999999999", "Unlisted fixture condition")          # absent from vocabulary

SYS = ("8480-6", "Systolic Blood Pressure")
DIA = ("8462-4", "Diastolic Blood Pressure")
WEIGHT = ("29463-7", "Body Weight")
HBA1C = ("4548-4", "Hemoglobin A1c/Hemoglobin.total in Blood")
SMOKING = ("72166-2", "Tobacco smoking status")
UNKNOWN_OBS = ("99999-9", "Unlisted fixture score")

LISINOPRIL = ("314076", "lisinopril 10 MG Oral Tablet")
AMLODIPINE = ("197361", "amlodipine 5 MG Oral Tablet")             # non-standard source -> Maps to
METFORMIN = ("860975", "24 HR metformin hydrochloride 500 MG Extended Release Oral Tablet")


class Batch:
    def __init__(self) -> None:
        self.patients: list[list[str]] = []
        self.encounters: list[list[str]] = []
        self.conditions: list[list[str]] = []
        self.medications: list[list[str]] = []
        self.observations: list[list[str]] = []
        self.organizations: list[list[str]] = []
        self.raw_lines: dict[str, list[tuple[int, str]]] = {}   # file -> (insert position, literal line)

    def patient(self, n, birth, *, death="", race="white", eth="nonhispanic", gender="F", state="Massachusetts"):
        self.patients.append([
            pid(n), birth, death, f"FAKE-SSN-{n:02d}", f"FAKE-DL-{n:02d}", "", "", f"Fixture{n:02d}", "",
            f"Person{n:02d}", "", "", "S", race, eth, gender, "Nowhere Massachusetts US",
            f"{n} Fictional Street", "Springfield", state, "Hampden County", "25013", "01101", "42.1", "-72.5",
            "1000.00", "500.00", "50000",
        ])

    def encounter(self, n, k, start, *, stop=None, cls="ambulatory", org=ORG1):
        code, desc = {
            "wellness": ("185349003", "Encounter for check up (procedure)"),
            "emergency": ("50849002", "Emergency room admission (procedure)"),
            "inpatient": ("32485007", "Hospital admission (procedure)"),
        }.get(cls, ("185345009", "Encounter for symptom (procedure)"))
        if stop is None:
            stop = start[:11] + "23:30:00Z" if start.endswith("Z") and start[11:13] < "23" else ""
        self.encounters.append([
            eid(n, k), start, stop, pid(n), org, "", "", cls, code, desc, "129.16", "129.16", "0.00", "", "",
        ])

    def condition(self, n, start, code, *, stop="", enc=None, system=SNOMED_URI):
        self.conditions.append([start, stop, pid(n), enc or "", system, code[0], code[1]])

    def medication(self, n, start, code, *, stop="", enc=None, dispenses="1"):
        self.medications.append([start, stop, pid(n), "", enc or "", code[0], code[1], "10.00", "0.00",
                                 dispenses, "10.00", "", ""])

    def observation(self, n, date, code, value, units, *, enc=None, cat="vital-signs", typ="numeric"):
        self.observations.append([date, pid(n), enc or "", cat, code[0], code[1], value, units, typ])

    def orgs(self, clinic_name="Fixture Wellness Clinic"):
        self.organizations = [
            [ORG1, "Fixture General Hospital", "1 Hospital Way", "Springfield", "MA", "01101", "42.1", "-72.5",
             "555-0100", "0", "0", "ignored"],
            [ORG2, clinic_name, "2 Clinic Road", "Boston", "MA", "02101", "42.3", "-71.0", "555-0101", "0", "0",
             "ignored"],
        ]


def person_rows(b: Batch, n: int, *, variant: str = "A") -> None:
    """Emit every row for person n. `variant` selects batch-B corrections."""
    e = lambda k: eid(n, k)  # noqa: E731
    if n == 1:  # C1+C2 member; old encounter outside window. Batch B: Type 1 race correction.
        b.patient(1, "1970-03-15", race="asian" if variant == "B" else "white")
        b.encounter(1, 1, "2016-05-01T09:00:00Z", cls="wellness")
        b.encounter(1, 2, "2026-05-10T14:00:00Z")
        b.condition(1, "2016-05-01", HTN_E, enc=e(1))
        b.medication(1, "2016-05-01T09:30:00Z", LISINOPRIL, enc=e(1), dispenses="120")
        b.observation(1, "2026-05-10T14:10:00Z", SYS, "150", "mm[Hg]", enc=e(2))
        b.observation(1, "2026-05-10T14:10:00Z", DIA, "95", "mm[Hg]", enc=e(2))
    elif n == 2:  # Birthday exactly on D: 18 on D -> eligible.
        b.patient(2, "2008-06-30", race="black", gender="M")
        b.encounter(2, 1, "2026-06-01T10:00:00Z", org=ORG2)
        b.condition(2, "2026-06-01", HTN_S, enc=e(1))
        b.observation(2, "2026-06-01T10:15:00Z", SYS, "145", "mm[Hg]", enc=e(1))
        b.observation(2, "2026-06-01T10:15:00Z", DIA, "90", "mm[Hg]", enc=e(1))
    elif n == 3:  # One day too young on D.
        b.patient(3, "2008-07-01")
        b.encounter(3, 1, "2026-06-15T09:00:00Z")
        b.condition(3, "2026-06-15", HTN_E, enc=e(1))
        b.observation(3, "2026-06-15T09:10:00Z", SYS, "160", "mm[Hg]", enc=e(1))
    elif n == 4:  # Death on D: not alive at the end of D.
        b.patient(4, "1950-01-20", death="2026-06-30", gender="M")
        b.encounter(4, 1, "2026-06-20T08:00:00Z", stop="2026-06-23T08:00:00Z", cls="inpatient")
        b.condition(4, "2015-06-20", HTN_E, enc=e(1))
        b.observation(4, "2026-06-20T09:00:00Z", SYS, "170", "mm[Hg]", enc=e(1))
    elif n == 5:  # Resolved condition: stopped the day before D.
        b.patient(5, "1980-08-08")
        b.encounter(5, 1, "2026-01-15T09:00:00Z")
        b.encounter(5, 2, "2026-06-10T09:00:00Z")
        b.condition(5, "2018-02-01", HTN_E, stop="2026-06-29")
        b.observation(5, "2026-06-10T09:10:00Z", SYS, "150", "mm[Hg]", enc=e(2))
    elif n == 6:  # Condition stop exactly on D (still active); no systolic at all.
        b.patient(6, "1965-11-30", gender="M")
        b.encounter(6, 1, "2026-02-02T11:00:00Z")
        b.condition(6, "2020-02-02", HTN_E, stop="2026-06-30")
        b.observation(6, "2026-02-02T11:10:00Z", WEIGHT, "88.2", "kg", enc=e(1))
    elif n == 7:  # Condition starting after D; encounter after D does not count.
        b.patient(7, "1990-04-04", eth="hispanic")
        b.encounter(7, 1, "2026-03-01T09:00:00Z")
        b.encounter(7, 2, "2026-07-05T09:00:00Z")
        b.condition(7, "2026-07-05", HTN_E, enc=e(2))
        b.observation(7, "2026-07-05T09:10:00Z", SYS, "150", "mm[Hg]", enc=e(2))
    elif n == 8:  # Duplicate diagnosis rows on one encounter, one-to-many mapping, 3 encounters, 141.
        b.patient(8, "1975-12-12", race="asian", gender="M")
        b.encounter(8, 1, "2025-09-01T08:00:00Z")
        b.encounter(8, 2, "2026-01-10T08:00:00Z")
        b.encounter(8, 3, "2026-04-20T08:00:00Z")
        b.condition(8, "2025-09-01", HTN_E, enc=e(1))
        b.condition(8, "2025-09-01", HTN_E, enc=e(1))   # identical row: multiplicity preserved
        b.condition(8, "2025-09-01", T2DM, enc=e(1))
        b.condition(8, "2026-01-10", NEURO, enc=e(2))
        b.medication(8, "2025-09-01T08:30:00Z", METFORMIN, enc=e(1), dispenses="12")
        b.observation(8, "2026-04-20T08:05:00Z", SYS, "141", "mm[Hg]", enc=e(3))
        b.observation(8, "2026-04-20T08:05:00Z", DIA, "88", "mm[Hg]", enc=e(3))
        b.observation(8, "2026-04-20T08:06:00Z", HBA1C, "7.1", "%", enc=e(3), cat="laboratory")
    elif n == 9:  # Two encounters. Batch B: late-arriving third encounter dated before the latest.
        b.patient(9, "1985-02-28")
        b.encounter(9, 1, "2025-08-15T09:00:00Z")
        b.encounter(9, 2, "2026-05-05T09:00:00Z")
        b.observation(9, "2025-08-15T09:05:00Z", WEIGHT, "70", "kg", enc=e(1))
        b.observation(9, "2026-05-05T09:05:00Z", WEIGHT, "71", "kg", enc=e(2))
        if variant == "B":
            b.encounter(9, 3, "2025-12-01T09:00:00Z")
            b.observation(9, "2025-12-01T09:05:00Z", WEIGHT, "70.5", "kg", enc=e(3))
    elif n == 10:  # Encounters exactly on both window boundaries; open-ended final encounter.
        b.patient(10, "1960-07-07", gender="M")
        b.encounter(10, 1, "2025-07-01T00:00:00Z")
        b.encounter(10, 2, "2025-12-25T12:00:00Z", cls="emergency")
        b.encounter(10, 3, "2026-06-30T23:59:59Z", stop="")
        b.observation(10, "2025-07-01T00:10:00Z", WEIGHT, "90", "kg", enc=e(1))
        b.observation(10, "2025-12-25T12:10:00Z", WEIGHT, "91", "kg", enc=e(2))
    elif n == 11:  # One encounter one second before the window + two inside; plus a quarantined row.
        b.patient(11, "1972-09-09")
        b.encounter(11, 1, "2025-06-30T23:59:59Z", stop="")
        b.encounter(11, 2, "2025-10-10T10:00:00Z")
        b.encounter(11, 3, "2026-03-03T10:00:00Z")
        b.observation(11, "2025-10-10T10:05:00Z", WEIGHT, "65", "kg", enc=e(2))
    elif n == 12:  # Old high systolic followed by a recent lower value; absent encounter link.
        b.patient(12, "1958-05-05", gender="M")
        b.encounter(12, 1, "2026-04-10T09:00:00Z")
        b.encounter(12, 2, "2026-06-10T09:00:00Z")
        b.condition(12, "2019-01-01", HTN_S)
        b.observation(12, "2026-04-10T09:05:00Z", SYS, "170", "mm[Hg]", enc=e(1))
        b.observation(12, "2026-06-10T09:05:00Z", SYS, "130", "mm[Hg]", enc=e(2))
    elif n == 13:  # Latest value exactly 140. Batch B: keyless correction to 141.
        b.patient(13, "1968-10-10")
        b.encounter(13, 1, "2026-05-20T09:00:00Z")
        b.condition(13, "2021-01-01", HTN_E)
        b.observation(13, "2026-05-20T09:05:00Z", SYS, "141" if variant == "B" else "140", "mm[Hg]", enc=e(1))
        b.observation(13, "2026-05-20T09:05:00Z", DIA, "85", "mm[Hg]", enc=e(1))
    elif n == 14:  # Missing numeric value in window; older high value outside the 89-day window.
        b.patient(14, "1955-03-03", gender="M")
        b.encounter(14, 1, "2026-03-01T09:00:00Z")
        b.encounter(14, 2, "2026-06-15T09:00:00Z")
        b.condition(14, "2010-01-01", HTN_E)
        b.observation(14, "2026-03-01T09:05:00Z", SYS, "160", "mm[Hg]", enc=e(1))
        b.observation(14, "2026-06-15T09:05:00Z", SYS, "", "mm[Hg]", enc=e(2))
    elif n == 15:  # Unrecognised unit for systolic.
        b.patient(15, "1978-06-06")
        b.encounter(15, 1, "2026-06-01T09:00:00Z")
        b.condition(15, "2012-01-01", HTN_E)
        b.observation(15, "2026-06-01T09:05:00Z", SYS, "155", "cm[H2O]", enc=e(1))
    elif n == 16:  # Tied timestamps (same instant, different offsets) -> deterministic tie-break.
        b.patient(16, "1962-02-14", gender="M")
        b.encounter(16, 1, "2026-06-20T06:00:00-04:00")
        b.condition(16, "2016-01-01", HTN_E)
        b.observation(16, "2026-06-20T10:00:00Z", SYS, "150", "mm[Hg]", enc=e(1))
        b.observation(16, "2026-06-20T06:00:00-04:00", SYS, "145", "mm[Hg]", enc=e(1))
    elif n == 17:  # Categorical observation; later non-numeric systolic must not replace the valid one.
        b.patient(17, "1988-01-01")
        b.encounter(17, 1, "2026-06-25T09:00:00Z")
        b.encounter(17, 2, "2026-06-26T09:00:00Z")
        b.condition(17, "2025-01-01", HTN_E)
        b.observation(17, "2026-06-25T09:00:00Z", SYS, "142", "mm[Hg]", enc=e(1))
        b.observation(17, "2026-06-26T09:00:00Z", SYS, "not recorded", "mm[Hg]", enc=e(2))
        b.observation(17, "2026-06-25T09:02:00Z", SMOKING, "Never smoked tobacco (finding)", "", enc=e(1),
                      cat="survey", typ="text")
    elif n == 18:  # Unknown source concepts (condition and observation).
        b.patient(18, "1992-12-31", gender="M")
        b.encounter(18, 1, "2026-02-10T09:00:00Z")
        b.condition(18, "2026-02-10", UNKNOWN_COND, enc=e(1))
        b.observation(18, "2026-02-10T09:05:00Z", UNKNOWN_OBS, "12", "{score}", enc=e(1))
    elif n == 19:  # Wrong-domain mapping, Maps-to-value, non-standard drug source, laboratory value.
        b.patient(19, "1983-03-17")
        b.encounter(19, 1, "2026-01-05T09:00:00Z")
        b.encounter(19, 2, "2026-05-05T09:00:00Z")
        b.condition(19, "2026-01-05", EMPLOY, enc=e(1))
        b.condition(19, "2026-05-05", VIOLENCE, enc=e(2))
        b.medication(19, "2026-05-05T10:00:00Z", AMLODIPINE, stop="2026-06-04T10:00:00Z", enc=e(2),
                     dispenses="30")
        b.observation(19, "2026-05-05T09:05:00Z", HBA1C, "5.6", "%", enc=e(2), cat="laboratory")
    elif n == 20:  # Missing optional organization -> Unknown organization in the star.
        b.patient(20, "1970-10-20", gender="M")
        b.encounter(20, 1, "2026-04-04T09:00:00Z", org="")
        b.condition(20, "2026-04-04", HTN_S, enc=e(1))
        b.observation(20, "2026-04-04T09:05:00Z", SYS, "138", "mm[Hg]", enc=e(1))
    elif n == 21:  # Invalid visit reference; blank SYSTEM uses the table default; orphan rows elsewhere.
        b.patient(21, "1945-07-15")
        b.encounter(21, 1, "2026-03-15T09:00:00Z")
        b.condition(21, "2026-03-15", PREDIAB, enc=eid(99, 99), system="")
        b.observation(21, "2026-03-15T09:05:00Z", WEIGHT, "58", "kg", enc=e(1))
    elif n == 22:  # A person with no events at all.
        b.patient(22, "1999-09-19", gender="M")
    elif n == 23:  # Leap-day birth; quoted, multi-line, Unicode text value.
        b.patient(23, "1980-02-29")
        b.encounter(23, 1, "2026-06-05T09:00:00Z")
        b.observation(23, "2026-06-05T09:05:00Z", SMOKING,
                      'Former smoker, "quit" 2019\nsee note – Ångström café', "",
                      enc=e(1), cat="survey", typ="text")
        b.observation(23, "2026-06-05T09:06:00Z", WEIGHT, "61.5", "kg", enc=e(1))
    elif n == 24:  # Four encounters, two conditions each (join must not inflate). Batch B: all events removed.
        b.patient(24, "1966-06-16", gender="M")
        if variant != "B":
            for k, start in enumerate(["2025-08-08", "2025-11-11", "2026-02-02", "2026-05-05"], start=1):
                b.encounter(24, k, f"{start}T09:00:00Z")
                b.condition(24, start, T2DM, enc=e(k))
                b.condition(24, start, PREDIAB, enc=e(k))
    elif n == 25:  # C1 member with only an out-of-window measurement. Batch B: person removed entirely.
        if variant != "B":
            b.patient(25, "1977-07-27")
            b.encounter(25, 1, "2026-01-20T09:00:00Z")
            b.condition(25, "2024-01-01", HTN_E)
            b.observation(25, "2026-01-20T09:05:00Z", SYS, "150", "mm[Hg]", enc=e(1))
    elif n == 26:  # Batch B insert: new C1 person with a 139 systolic.
        b.patient(26, "1990-10-10", gender="M")
        b.encounter(26, 1, "2026-06-12T09:00:00Z")
        b.condition(26, "2026-06-12", HTN_S, enc=e(1))
        b.observation(26, "2026-06-12T09:05:00Z", SYS, "139", "mm[Hg]", enc=e(1))
        b.medication(26, "2026-06-12T09:30:00Z", LISINOPRIL, enc=e(1), dispenses="30")


def write_csv(path: Path, header: list[str], rows: list[list[str]], raw_lines=()) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    lines = []
    for row in rows:
        row_buffer = io.StringIO(newline="")
        csv.writer(row_buffer, lineterminator="\n").writerow(row)
        lines.append(row_buffer.getvalue())
    for position, literal in raw_lines:
        lines.insert(position, literal + "\n")
    path.write_bytes((buffer.getvalue() + "".join(lines)).encode("utf-8"))


def emit(batch: Batch, directory: Path, *, order: str = "natural", seed: int = 0) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    tables = {
        "patients.csv": (PATIENT_HEADER, batch.patients),
        "encounters.csv": (ENCOUNTER_HEADER, batch.encounters),
        "conditions.csv": (CONDITION_HEADER, batch.conditions),
        "medications.csv": (MEDICATION_HEADER, batch.medications),
        "observations.csv": (OBSERVATION_HEADER, batch.observations),
        "organizations.csv": (ORGANIZATION_HEADER, batch.organizations),
    }
    rng = random.Random(seed)
    for filename, (header, rows) in tables.items():
        rows = list(rows)
        if order == "reversed":
            rows.reverse()
        elif order == "shuffled":
            rng.shuffle(rows)
        write_csv(directory / filename, header, rows, batch.raw_lines.get(filename, ()))


def generator_block() -> dict:
    script = Path(__file__).read_bytes().replace(b"\r\n", b"\n")
    return {
        "name": "cohortwarehouse-fixture-builder",
        "version": "1",
        "seed": 20260915,
        "arguments": ["scripts/build_fixture.py"],
        "config_sha256": hashlib.sha256(script).hexdigest(),
        "simulation_end_date": AS_OF,
    }


def build_batches() -> None:
    if FIXTURE.exists():
        for child in ("batch_A", "batch_B", "batch_C"):
            shutil.rmtree(FIXTURE / child, ignore_errors=True)

    # ---------------------------------------------------------------- A: full baseline snapshot
    a = Batch()
    a.orgs()
    for n in range(1, 26):
        person_rows(a, n)
    # Orphans: rows referencing a patient that does not exist (excluded with a reason, never Unknown).
    a.encounter(99, 1, "2026-02-01T09:00:00Z")
    a.condition(99, "2026-02-01", HTN_E, enc=eid(99, 1))
    # Quarantine case 1: invalid required timestamp.
    a.encounters.append([eid(11, 9), "not-a-date", "", pid(11), ORG1, "", "", "ambulatory", "185345009",
                         "Encounter for symptom (procedure)", "129.16", "129.16", "0.00", "", ""])
    invalid_ts_record = len(a.encounters)
    # Quarantine case 2: malformed row (unquoted comma -> 10 fields) inserted mid-file.
    malformed_position = 5
    a.raw_lines["observations.csv"] = [(
        malformed_position,
        f"2026-05-10T14:20:00Z,{pid(10)},{eid(10, 1)},vital-signs,29463-7,Body Weight, adult,80,kg,numeric",
    )]
    emit(a, FIXTURE / "batch_A")
    write_manifest(FIXTURE / "batch_A", build_manifest(
        FIXTURE / "batch_A", dataset_id=DATASET, batch_id="fixture-A", source_revision=1, as_of_date=AS_OF,
        delivered_at="2026-07-01T04:30:00Z", generator=generator_block(), delivery_kind="scheduled",
        expected_quarantine=[
            {"file": "encounters", "record_number": invalid_ts_record, "reason": "invalid_timestamp"},
            {"file": "observations", "record_number": malformed_position + 1, "reason": "field_count_mismatch"},
        ],
        notes="Baseline full snapshot of the 25-person fixture.",
    ))

    # ---------------------------------------------------------------- B: scoped changes, reversed row order
    scope = [pid(n) for n in (1, 9, 13, 24, 25, 26)]
    b = Batch()
    b.orgs(clinic_name="Fixture Wellness Clinic (renamed)")
    for n in (1, 9, 13, 24, 25, 26):
        person_rows(b, n, variant="B")
    emit(b, FIXTURE / "batch_B", order="reversed")
    write_manifest(FIXTURE / "batch_B", build_manifest(
        FIXTURE / "batch_B", dataset_id=DATASET, batch_id="fixture-B", source_revision=2, as_of_date=AS_OF,
        delivered_at="2026-07-02T04:30:00Z", generator=generator_block(), replacement_mode="scoped",
        patient_scope=scope, delivery_kind="scheduled",
        notes="Type 1 correction (P01), late encounter (P09), keyless correction (P13), all events removed "
              "(P24), person removed (P25), new person (P26), organization renamed.",
    ))

    # ---------------------------------------------------------------- C: B's clinical content again, shuffled
    emit(b, FIXTURE / "batch_C", order="shuffled", seed=7)
    write_manifest(FIXTURE / "batch_C", build_manifest(
        FIXTURE / "batch_C", dataset_id=DATASET, batch_id="fixture-C", source_revision=3, as_of_date=AS_OF,
        delivered_at="2026-07-03T04:30:00Z", generator=generator_block(), replacement_mode="scoped",
        patient_scope=scope, delivery_kind="scheduled",
        notes="Identical clinical content to fixture-B in a different row order: a new delivery, zero changes.",
    ))


# ---------------------------------------------------------------------------------------------- vocabulary
def build_vocabulary() -> None:
    """A deliberately FICTIONAL vocabulary. Concept IDs live in the >2,000,000,000 local range and
    names/relationships are invented; it only exercises mapping mechanics and must never be used
    for a release (PRD Section 12.1, vocabulary test boundary)."""
    shutil.rmtree(VOCAB, ignore_errors=True)
    VOCAB.mkdir(parents=True)
    (VOCAB / "TEST_ONLY_FICTIONAL_VOCABULARY.txt").write_bytes(
        b"FICTIONAL test-only vocabulary for CohortWarehouse CI and fixtures.\n"
        b"Concept IDs and relationships are invented. Not derived from, and not a substitute for,\n"
        b"the OHDSI Standardized Vocabularies. Cannot satisfy the release validation profile.\n"
    )
    start, end = "19700101", "20991231"
    concepts = [
        # id, name, domain, vocabulary, class, standard, code, invalid_reason
        (2000000001, "Fictional metadata concept", "Metadata", "None", "Undefined", "", "FICT-NONE", ""),
        (2000000101, "MALE", "Gender", "Gender", "Gender", "S", "M", ""),
        (2000000102, "FEMALE", "Gender", "Gender", "Gender", "S", "F", ""),
        (2000000111, "White", "Race", "Race", "Race", "S", "5", ""),
        (2000000112, "Black or African American", "Race", "Race", "Race", "S", "3", ""),
        (2000000113, "Asian", "Race", "Race", "Race", "S", "2", ""),
        (2000000114, "American Indian or Alaska Native", "Race", "Race", "Race", "S", "1", ""),
        (2000000115, "Native Hawaiian or Other Pacific Islander", "Race", "Race", "Race", "S", "4", ""),
        (2000000121, "Hispanic or Latino", "Ethnicity", "Ethnicity", "Ethnicity", "S", "Hispanic", ""),
        (2000000122, "Not Hispanic or Latino", "Ethnicity", "Ethnicity", "Ethnicity", "S", "Not Hispanic", ""),
        (2000000131, "Inpatient Visit", "Visit", "Visit", "Visit", "S", "IP", ""),
        (2000000132, "Outpatient Visit", "Visit", "Visit", "Visit", "S", "OP", ""),
        (2000000133, "Emergency Room Visit", "Visit", "Visit", "Visit", "S", "ER", ""),
        (2000000141, "EHR", "Type Concept", "Type Concept", "Type Concept", "S", "OMOP4976890", ""),
        (2000000151, "OMOP CDM Version 5.4", "Metadata", "CDM", "CDM", "S", "CDM v5.4", ""),
        (2000000161, "millimeter mercury column", "Unit", "UCUM", "Unit", "S", "mm[Hg]", ""),
        (2000000162, "kilogram", "Unit", "UCUM", "Unit", "S", "kg", ""),
        (2000000163, "percent", "Unit", "UCUM", "Unit", "S", "%", ""),
        (2000000164, "centimeter of water", "Unit", "UCUM", "Unit", "S", "cm[H2O]", ""),
        (2000000165, "score", "Unit", "UCUM", "Unit", "S", "{score}", ""),
        (2000001001, "Essential hypertension", "Condition", "SNOMED", "Disorder", "S", "59621000", ""),
        (2000001002, "Hypertensive disorder, systemic arterial", "Condition", "SNOMED", "Disorder", "S",
         "38341003", ""),
        (2000001003, "Type 2 diabetes mellitus", "Condition", "SNOMED", "Disorder", "S", "44054006", ""),
        (2000001004, "Prediabetes", "Condition", "SNOMED", "Clinical Finding", "S", "15777000", ""),
        (2000001005, "Full-time employment", "Observation", "SNOMED", "Clinical Finding", "S", "160903007", ""),
        (2000001006, "Neuropathy due to type 2 diabetes mellitus", "Condition", "SNOMED", "Disorder", "",
         "368581000119106", ""),
        (2000001007, "Diabetic neuropathy", "Condition", "SNOMED", "Disorder", "S", "230572002", ""),
        (2000001008, "Reports of violence in the environment", "Observation", "SNOMED", "Clinical Finding", "",
         "424393004", ""),
        (2000001009, "Fictional environment finding", "Observation", "SNOMED", "Clinical Finding", "S",
         "FICT-OBS-1", ""),
        (2000001010, "Fictional violence value", "Meas Value", "SNOMED", "Qualifier Value", "S", "FICT-VAL-1", ""),
        (2000001099, "Fictional deprecated target", "Condition", "SNOMED", "Disorder", "", "FICT-DEPR-1", "D"),
        (2000002001, "Systolic blood pressure", "Measurement", "LOINC", "Clinical Observation", "S", "8480-6", ""),
        (2000002002, "Diastolic blood pressure", "Measurement", "LOINC", "Clinical Observation", "S", "8462-4", ""),
        (2000002003, "Body weight", "Measurement", "LOINC", "Clinical Observation", "S", "29463-7", ""),
        (2000002004, "Hemoglobin A1c/Hemoglobin.total in Blood", "Measurement", "LOINC", "Lab Test", "S",
         "4548-4", ""),
        (2000002005, "Tobacco smoking status", "Observation", "LOINC", "Clinical Observation", "S", "72166-2", ""),
        (2000003001, "lisinopril 10 MG Oral Tablet", "Drug", "RxNorm", "Clinical Drug", "S", "314076", ""),
        (2000003002, "amlodipine 5 MG Oral Tablet (fictional non-standard)", "Drug", "RxNorm", "Clinical Drug", "",
         "197361", ""),
        (2000003003, "24 HR metformin hydrochloride 500 MG Extended Release Oral Tablet", "Drug", "RxNorm",
         "Clinical Drug", "S", "860975", ""),
        (2000003004, "Fictional amlodipine standard", "Drug", "RxNorm", "Clinical Drug", "S", "FICT-RX-1", ""),
    ]
    rels = [
        (2000001006, 2000001007, "Maps to", ""),
        (2000001006, 2000001003, "Maps to", ""),
        (2000001006, 2000001099, "Maps to", "D"),       # deprecated relationship must be ignored
        (2000001008, 2000001009, "Maps to", ""),
        (2000001008, 2000001010, "Maps to value", ""),
        (2000003002, 2000003004, "Maps to", ""),
    ]
    # Standard concepts map to themselves, as in Athena packages.
    rels += [(c[0], c[0], "Maps to", "") for c in concepts if c[5] == "S" and c[3] in {"SNOMED", "LOINC", "RxNorm"}]

    def tsv(name: str, header: list[str], rows: list[tuple]) -> None:
        body = "\t".join(header) + "\n" + "".join("\t".join(str(v) for v in row) + "\n" for row in rows)
        (VOCAB / name).write_bytes(body.encode("utf-8"))

    tsv("CONCEPT.csv",
        ["concept_id", "concept_name", "domain_id", "vocabulary_id", "concept_class_id", "standard_concept",
         "concept_code", "valid_start_date", "valid_end_date", "invalid_reason"],
        [(c[0], c[1], c[2], c[3], c[4], c[5], c[6], start, "20240101" if c[7] else end, c[7]) for c in concepts])
    tsv("CONCEPT_RELATIONSHIP.csv",
        ["concept_id_1", "concept_id_2", "relationship_id", "valid_start_date", "valid_end_date", "invalid_reason"],
        sorted((r[0], r[1], r[2], start, "20240101" if r[3] else end, r[3]) for r in rels))
    vocabularies = ["SNOMED", "LOINC", "RxNorm", "UCUM", "Gender", "Race", "Ethnicity", "Visit", "Type Concept",
                    "CDM"]
    tsv("VOCABULARY.csv",
        ["vocabulary_id", "vocabulary_name", "vocabulary_reference", "vocabulary_version", "vocabulary_concept_id"],
        [("None", "Fictional test vocabulary", "tests/fixtures/vocabulary", "CW-TEST-FICTIONAL-2026.09",
          2000000001)] + [(v, f"{v} (fictional test subset)", "fictional", "CW-TEST-FICTIONAL", 2000000001)
                          for v in vocabularies])
    domains = ["Condition", "Drug", "Measurement", "Observation", "Visit", "Gender", "Race", "Ethnicity",
               "Type Concept", "Unit", "Metadata", "Meas Value"]
    tsv("DOMAIN.csv", ["domain_id", "domain_name", "domain_concept_id"],
        [(d, d, 2000000001) for d in domains])
    classes = sorted({c[4] for c in concepts})
    tsv("CONCEPT_CLASS.csv", ["concept_class_id", "concept_class_name", "concept_class_concept_id"],
        [(c, c, 2000000001) for c in classes])
    tsv("RELATIONSHIP.csv",
        ["relationship_id", "relationship_name", "is_hierarchical", "defines_ancestry", "reverse_relationship_id",
         "relationship_concept_id"],
        [("Maps to", "Non-standard to Standard map (OMOP)", "0", "0", "Mapped from", 2000000001),
         ("Mapped from", "Standard to Non-standard map (OMOP)", "0", "0", "Maps to", 2000000001),
         ("Maps to value", "Non-standard to value map (OMOP)", "0", "0", "Value mapped from", 2000000001),
         ("Value mapped from", "Value to non-standard map (OMOP)", "0", "0", "Maps to value", 2000000001)])


if __name__ == "__main__":
    build_batches()
    build_vocabulary()
    summary = {p.parent.name: json.loads(p.read_text(encoding="utf-8"))["files"] for p in FIXTURE.glob("*/manifest.json")}
    print(json.dumps({k: {f: v["records"] for f, v in files.items()} for k, files in sorted(summary.items())}, indent=2))
