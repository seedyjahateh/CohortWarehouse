# Evidence: `cohortwarehouse_daily` on a live Airflow 3.1 deployment

**Date:** 2026-09-18 · **Runtime:** `compose.yml` profile `airflow` — image `cohortwarehouse-airflow:local`
built from `apache/airflow:3.1.0-python3.12` (pinned digest) with dbt in its own virtualenv; LocalExecutor;
separate PostgreSQL metadata database; warehouse on the compose network.

## Result

| DAG run | Trigger | Outcome |
|---|---|---|
| `scheduled__2026-09-18T05:15:00+00:00` | created on unpause (`catchup=False`) | **failed, as designed**: no delivery manifest existed for that interval, so `resolve_manifest` failed promptly after its retries (Section 9.3: "missing delivery fails promptly") |
| `manual__…FNACyGaR` | `{"batch_id": "fixture-A"}` | failed at `check_delivery_freshness` — bug 3 below |
| `manual__…MiBNOmNr` | `{"batch_id": "fixture-A"}` | first attempt of the dbt stage failed (bug 2); **recovered on Airflow retry** once the DAG was fixed, then **succeeded** and published `r0001` |
| `manual__…VlQo7ZIQ` | `{"batch_id": "fixture-A"}` | **all 11 tasks succeeded on the first try**; published `r0002`; docs generated |

After the runs, the least-privilege BI login reads `bi.bi_cohort_membership` as **C1 = 12, C2 = 5, C3 = 3**, the
hand-derived fixture-A expectation. `ops.release_event` shows `published` and `docs_generated` for both
releases, and `ops.pipeline_run.trigger = airflow` for both runs.

## Defects found only by running it (all fixed)

1. **Shared JWT secret missing.** Airflow 3 signs task-execution tokens; each container generated its own
   secret, so every task was rejected by the API server ("Invalid auth token: Signature verification failed")
   and runs stayed queued. `compose.yml` now passes `AIRFLOW__API_AUTH__JWT_SECRET` (from `.env`) to every
   component.
2. **Reserved argument name.** Task functions took a parameter named `run_id`, which Airflow 3 reserves as a
   context key ("The key 'run_id' in args is a part of kwargs and therefore reserved"). The DAG parsed and
   passed CI's structure test but failed at execution. Parameters are now `pipeline_run_id`, and
   `tests/airflow/test_dag.py::test_task_arguments_do_not_shadow_airflow_context_keys` guards it in CI.
3. **Freshness checked the wrong dataset.** `check_delivery_freshness` used the DAG's default dataset
   (`synthea_demo`) even when a manual run targeted a batch from another dataset, and correctly-but-wrongly
   reported "no delivery has ever been loaded". It now resolves the dataset from the batch being processed.
4. `record_run_summary` (trigger rule `all_done`) crashed when no pipeline run existed; it now summarises
   runs that failed before `prepare_changed_persons`.

## Still open
- **NFR-04** (ten consecutive scheduled runs meeting the 06:00 UTC deadline) requires a delivery process that
  drops a manifest per day and a host that stays up; not attempted.
- E-mail/Slack alerting is P1; failures are recorded in `ops.alert_event` and task logs.
