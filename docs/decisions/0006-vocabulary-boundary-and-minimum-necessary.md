# 0006 — Fictional test vocabulary boundary; minimum-necessary ingestion

**Status:** accepted · **Date:** 2026-09-17 · **Requirements:** GOV-03, Section 10, Section 12.1

## Vocabulary
- The repository ships only `tests/fixtures/vocabulary`: a deliberately **fictional** Athena-format package
  (concept ids ≥ 2,000,000,000, invented names/relationships, marker file, `FICTIONAL` in its version).
- `load-vocabulary` records `is_test_only`; the `release` validation profile fails
  `terminology:vocabulary_profile` whenever the current vocabulary is test-only. CI evidence is labelled
  "FICTIONAL test vocabulary" and cannot satisfy the real-vocabulary release gate.
- Real OHDSI Athena downloads stay outside Git (`vocabulary/` is ignored). Seeds resolve provenance, visit and
  demographic concepts **by vocabulary + code** at build time and record Athena reference ids only for
  documentation; nothing depends on hard-coded concept ids.
- **Open item:** the real-vocabulary integration run has not been executed in this environment (no Athena
  account access here). Until it is, OMOP concept correctness is demonstrated only mechanically.

## Minimum necessary
- Direct identifiers (`SSN, DRIVERS, PASSPORT, PREFIX/FIRST/MIDDLE/LAST/SUFFIX/MAIDEN, ADDRESS, CITY, ZIP, FIPS,
  LAT/LON, income/expense fields`) are declared `load: false` in the source contract: they are recognised,
  counted in `ops.batch_file.unloaded_columns`, and never written to any table — not even `raw`.
- Published marts use a pseudonymous id (truncated SHA-256 of dataset + source UUID) instead of the source
  UUID; OMOP `person_source_value` holds that pseudonym. Birth date is only in the protected star layer; BI
  exposes age at D. A dbt test and the Python gate both enforce a column denylist on everything BI can import.
- Synthetic provenance is a workflow contract (approved generator + `synthetic: true`), **not** a PHI detector.
