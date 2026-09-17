# Operations runbook

All commands run from the repository root with the project venv active (`.venv`). Times are UTC.

## Daily flow (Airflow `cohortwarehouse_daily`, 05:15 UTC)
`resolve_manifest → validate_and_load_raw → check_delivery_freshness → prepare_changed_persons →
dbt_build_staging_intermediate → dbt_build_star_omop → dbt_build_bi → quality_and_reconciliation_gate →
publish_release → generate_docs_and_release_report → record_run_summary`

- Delivery contract: `$CW_DELIVERY_ROOT/<dataset>/<YYYY-MM-DD>/manifest.json` available by 05:00 UTC.
- Transient I/O/DB failures retry twice, 5 minutes apart. Contract, quality and publication failures fail fast
  (`AirflowFailException`) — fix the cause, then clear the task or trigger a manual run.
- One writer: pool `cohortwarehouse_warehouse_write` (create it with 1 slot:
  `airflow pools set cohortwarehouse_warehouse_write 1 "warehouse writes"`), `max_active_runs=1`, and a
  PostgreSQL advisory lock shared with the CLI.
- The host's availability is part of the SLA. Missed deliveries and failed runs are recorded
  (`ops.alert_event`, Airflow logs); nothing claims service while the laptop sleeps.

## Equivalent CLI
```powershell
python -m cohortwarehouse ingest --manifest data/deliveries/synthea_demo/2026-09-17/manifest.json
python -m cohortwarehouse run --batch-id <batch_id>            # builds candidates + quality gate
python -m cohortwarehouse publish --validated-run <run_id>
python -m cohortwarehouse releases --dataset-id synthea_demo
```

## Diagnosing a failed run
1. `select run_id, status, mode, full_refresh_reason, error_class, error_message from ops.pipeline_run order by started_at desc limit 5;`
2. Blocking checks: `select check_id, status, observed, detail from ops.quality_result where run_id = '<run>' and status <> 'pass';`
3. dbt logs and results: `dbt/target/runs/<run_id>/<stage>/dbt_stdout.log`, `run_results.json`.
4. Failing test rows are stored in `work_audit.<test_name>` (transformer-readable).
5. Loader rejections: `select * from ops.load_attempt order by started_at desc limit 5;` quarantine rows:
   `select file_key, record_number, reason, detail from ops.quarantine where batch_id = '<batch>';`

The previous release stays current until a new publication commits — consumers are never on a partial build.

## Rerun / retry / backfill
- **Retry the same batch:** `python -m cohortwarehouse run --batch-id <batch>`. Changed people from the failed
  attempt are in `ops.pending_person` and are rebuilt automatically; nothing is duplicated.
- **Force a full rebuild:** add `--full-refresh` (also automatic when code, seeds, contract, vocabulary, as-of
  date, organization id set or dataset owner changed — see `full_refresh_reason`).
- **Historical inspection:** `run --batch-id <older batch> --validation-only` builds candidates for that revision;
  it can never be published. Run the current batch again afterwards to restore candidates.
- **Airflow manual run:** trigger with params `{"batch_id": "<already ingested>"}` or `{"manifest_path": "..."}`.

## Freshness
`python -m cohortwarehouse freshness --dataset-id <id> [--mode scheduled]` — measured on manifest
`delivered_at`, never on clinical event dates. Scheduled mode warns after 26 h and fails after 48 h.
`frozen_demo` (default in `config/pipeline.yml`) reports delivery age with an explicit FROZEN DEMO label.
