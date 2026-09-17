# 0001 — Stack, repository layout and scope boundaries

**Status:** accepted · **Date:** 2026-09-17 · **Requirements:** Section 1 (selected implementation), 9.1

## Decision
- PostgreSQL 16.10 (image pinned by digest), dbt Core 1.12.5 + dbt-postgres 1.11.0 (`requirements/dbt.lock`),
  Airflow 3.1.0 (image pinned by digest, dbt in its own venv inside the image), Power BI Desktop (Import).
- The Python loader/CLI is a single package `cohortwarehouse/` (the PRD sketch shows `ingestion/` and
  `scripts/` folders). One importable package lets the CLI, Airflow tasks and tests share exactly the same
  code paths (`python -m cohortwarehouse ...`). `scripts/` holds developer helpers (fixture builder, reset).
- Run context reaches dbt through environment variables (`CW_RUN_ID`, `CW_GIT_SHA`) rather than `--vars`.
  Changing a `--var` forces dbt to re-parse the whole project on every run (measured: ~50 s per invocation on
  the reference laptop); env vars only invalidate the files that use them.

## Consequences
- Airflow tasks import `cohortwarehouse` from the image; the DAG contains orchestration only.
- dbt artifacts are copied per run to `dbt/target/runs/<run_id>/<stage>/` for evidence while the working
  target path stays stable for partial parsing.
