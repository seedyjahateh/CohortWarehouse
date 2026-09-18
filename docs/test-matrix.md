# Test matrix (Section 11.1)

Status legend: **auto** = automated and executed in this repository's suites; **manual** = documented acceptance
step; **open** = not yet implemented/executed (a skipped or open P0 check is not a pass).

Suites: `unit` = `pytest tests/unit` (no DB) · `lifecycle` = `pytest tests/integration/test_fixture_lifecycle.py`
(disposable DB) · `loader` = `tests/integration/test_ingest_contract.py` · `dbt` = generic + singular dbt tests
run in every build and again in the quality gate · `gate` = Python checks in `cohortwarehouse/quality.py` ·
`dag` = `pytest tests/airflow` (pinned Airflow).

| Requirement | Check | Where | Status |
|---|---|---|---|
| ING-01 reproducible generation, manifest provenance | manifest schema + generator block; `generate` command | unit `test_manifest`, `cohortwarehouse/generate.py` | auto (manifest) / **open** (Synthea run not executed here) |
| ING-02 required files; header-only valid | preflight missing file / hash mismatch | unit `test_preflight_detects_missing_file_and_hash_mismatch` | auto |
| ING-03 headers & required types; extras recorded | renamed column rejects batch; extras recorded | unit `test_contract`, loader `test_renamed_required_column_rejects_whole_batch` | auto |
| ING-04 COPY, quoting, Unicode, malformed rows | fixture multiline/Unicode value; field-count quarantine | lifecycle `test_01`, dbt cohort tests | auto |
| ING-05 source locators | `_batch_id`, `_record_number`, `_row_fingerprint` NOT NULL; lineage columns in marts | DDL constraints, `cw_event_crosswalk` | auto |
| ING-06 parsed = accepted + quarantined | DB check constraints + gate `source:file_reconciliation` | gate | auto |
| ING-07 synthetic provenance | non-synthetic and unapproved generator rejected before load | unit + loader tests | auto |
| Transactional batch | count mismatch in 5th file rolls back all files | loader `test_declared_count_mismatch_rolls_back_every_file` | auto |
| Idempotent ingestion | identical replay no-op; batch id reuse refused; monotonic revisions | lifecycle `test_01`, loader `test_revision_order_batch_reuse_and_scope_rules` | auto |
| STG-02 missing/invalid/zero distinct | `value_parse_status` accepted values; P14/P17 flags | dbt, lifecycle | auto |
| STG-03 orphans, unknown org, wrong-person visit (blocking) | ledger; key 0; wrong-person run blocked | dbt `assert_no_wrong_person_visit_links`, lifecycle `test_12` | auto |
| STG-04 multiplicity preserved | identical diagnosis rows keep 2 keys; C3 not inflated | dbt `assert_star_joins_do_not_inflate`, fixture P08/P24 | auto |
| STG-05 no unexplained loss | `assert_source_event_conservation`, `assert_omop_event_accounting` | dbt | auto |
| Keys: unique/not_null all PKs; compound grains | schema YAML generic tests | dbt | auto |
| Relationships incl. nullable FKs | `relationships` + `not_null` pairs | dbt | auto |
| Temporal rules | `end_not_before_start`, `assert_structural_dates_plausible`, observation period order | dbt | auto |
| Impossible source end dates kept, nulled, ledgered, imputed | fixture patient 06 (real Synthea defect shape) | lifecycle `test_02b` | auto |
| Terminology | `assert_omop_concepts_valid`, `assert_reference_and_cohort_concepts_resolve` | dbt | auto (fictional vocabulary) / **open** (real vocabulary) |
| MAP-06 coverage | gate `coverage:*` (cohort 100%, files ≥ 95%) | gate | auto (fictional vocabulary) |
| GOV-01 CDM column contracts | `assert_omop_columns_match_official_ddl` | dbt | auto |
| Cohort correctness (exact sets) | independent SQL = BI; OMOP = BI; hand-written `expected.yml` = BI after A, B, C | dbt + lifecycle `test_02/06/08` | auto |
| Incremental correctness | failed-run retry; replay zero change; incremental = full rebuild (content + keys) | lifecycle `test_05/06/08/09`, dbt `assert_incremental_slices_match_source` | auto |
| Failure behaviour | mid-load (rollback), mid-model (slice rollback), before publication, inside publication | loader + lifecycle `test_05/07/12` | auto |
| NFR-09 consistent publication | views + pointer in one transaction; injected failure leaves release unchanged | lifecycle `test_07` | auto |
| NFR-10 restore ≤ 15 min | restore r0001 and back with verification | lifecycle `test_10` | auto (fixture scale) / **open** (benchmark drill evidence) |
| US-08 access boundaries | reader denial matrix, no updates | lifecycle `test_04*` | auto |
| Governance: denylist, secrets | dbt `assert_bi_columns_minimum_necessary`, gate denylist, CI gitleaks | dbt/gate/CI | auto (CI secret scan runs on GitHub only) |
| Retention | dry-run keeps current/previous/pinned | lifecycle `test_11` | auto |
| Freshness | 26 h / 48 h thresholds, frozen-demo label | unit `test_freshness_and_ddl` | auto |
| DAG contract | schedule, order, params, retries, pool, no import I/O | dag | written; **executes in CI only** (Airflow not installed locally) |
| DOC gates | every model: description, grain, owner; published models tested; exposure covers BI | unit `test_dbt_project_documentation` | auto |
| BI-01..05, NFR-06/07 | measures, reconciliation scenarios, screenshots, Performance Analyzer | `bi/measures.dax`, `docs/metric-contracts.md` | **open** (PBIX not yet built) |
| ING-01 reproducible generation | two runs of the pinned configuration compared per file | `docs/evidence/generation-reproducibility.md` | auto-verified manually (content identical; record order is documented volatile metadata) |
| NFR-02 ≤ 5 min for a 5% change | measured 214 s build+gate at 1,183 people / 1.34M rows | `docs/benchmark.md` | **met for build + gate**; publication unmeasured (vocabulary gate) |
| NFR-01 ≤ 20 min load → publication | measured 620 s for load + build + gate, one run | `docs/benchmark.md` | **incomplete**: publication blocked by the fictional vocabulary; 3 runs not done |
| NFR-08 SQL cohort p95 ≤ 2 s | — | — | **open** |
| NFR-04 10 scheduled runs | Airflow evidence | Airflow | **open** |
