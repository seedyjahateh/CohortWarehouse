# ING-01 evidence: reproducible generation

**Measured:** 2026-09-17 · Synthea v3.3.0 (`synthea-with-dependencies.jar`,
SHA-256 `8ba04f7d73abadd5a377e41edf24c5c83935a1cb07c6d982cd5db731ef1cf445`, verified before every run) in the
pinned container `eclipse-temurin:17.0.16_8-jre-jammy@sha256:e90fd2b0…4e1f7`.

## Finding: pin the end date, not only the reference date

The first configuration passed `-r 20260630` (reference date) but no `-e` (end date). Synthea then simulates
up to the **wall clock**, so identical seeds produced different output on the same day:

| Run | encounters | observations |
|---|---|---|
| 1 (≈15:00 UTC) | 87,484 | 1,138,996 |
| 2 (≈21:05 UTC) | 87,488 | 1,139,160 |

`config/demo.yml` now pins both dates (`-r` and `-e` from `simulation_end_date`), and
`cohortwarehouse/generate.py` records every argument in the delivery manifest.

## Verification after the fix

Two independent runs of the same configuration (25 requested patients, seed 20260915, Massachusetts,
`simulation_end_date: 2026-06-30`), compared per file:

| File | Rows (run 1 / run 2) | Byte-identical | Identical as a sorted multiset |
|---|---|---|---|
| patients.csv | 27 / 27 | no | **yes** |
| encounters.csv | 1,729 / 1,729 | no | **yes** |
| conditions.csv | 945 / 945 | no | **yes** |
| medications.csv | 1,203 / 1,203 | no | **yes** |
| observations.csv | 17,792 / 17,792 | no | **yes** |
| organizations.csv | 94 / 94 | **yes** | yes |

**Documented volatile exporter metadata: record order.** Synthea generates people in parallel, so completed
records are appended in nondeterministic order. Clinical content is identical.

Row order is irrelevant to this warehouse by construction:
* event identity is a canonical content fingerprint plus an occurrence ordinal, not file position
  (`cohortwarehouse/fingerprint.py`, ADR 0002);
* the manifest counts *parsed records*, never physical line numbers;
* batch C of the fixture is batch B's content in shuffled order and must produce zero changed people —
  asserted by `tests/integration/test_fixture_lifecycle.py::test_08`.

## Reproducing this check

```powershell
# two deliveries from one pinned configuration, then compare sorted content per file
python -m cohortwarehouse generate --config <copy of config/demo.yml with a distinct dataset_id/output_root>
```
Compare each CSV as a sorted multiset (record order differs by design).
