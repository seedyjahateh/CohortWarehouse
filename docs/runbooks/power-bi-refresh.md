# Power BI Desktop refresh runbook (NFR-06, BI-05)

Local Desktop refresh is a **manual** step. No unattended refresh SLA is claimed.

## One-time setup
1. Install Power BI Desktop (Windows). Install nothing else: the PostgreSQL connector (Npgsql) ships with Desktop.
2. Create the report parameter **ReleaseSchema** (Text, required), e.g. `bi_r0003`.
3. Get Data → PostgreSQL database → Server `127.0.0.1:5433`, Database `cohortwarehouse`, Import mode,
   credentials: Database auth with the `CW_BI_READER_*` login (read-only; cannot see raw, staging or star).
4. For each table use Advanced Editor so every query reads the **same** parameterised schema:
   ```powerquery
   let
       Source = PostgreSQL.Database("127.0.0.1:5433", "cohortwarehouse"),
       Table  = Source{[Schema = ReleaseSchema, Item = "bi_cohort_membership"]}[Data],
       Stamped = Table.AddColumn(Table, "imported_at_utc", each DateTimeZone.UtcNow(), type datetimezone)
   in
       Stamped
   ```
   Tables: `bi_patient_snapshot`, `bi_cohort_definition`, `bi_cohort_membership`, `bi_cohort_month`,
   `bi_month`, `bi_member_evidence`, `bi_mapping_coverage`, `bi_release_status`, `bi_data_profile`.
   Add `imported_at_utc` to `bi_release_status` only (it is the BI import time shown on the Data trust page).
5. Relationships exactly as in `bi/measures.dax` header (single direction). Hide `*_key` columns.
6. Paste measures from `bi/measures.dax`. Set cohort slicer to single-select.
7. Put the label **"Synthetic data — demonstration only"** on every page.

## Each refresh (acceptance demo)
1. Note publication time: `python -m cohortwarehouse releases --dataset-id <id>` → current `bi_schema`.
2. Within 15 minutes: keep a copy of the previous `.pbix`; set `ReleaseSchema` to the new `bi_rNNNN`; Refresh.
3. Import must finish within 2 minutes (record the time).
4. Verify on the Data trust page: *Imported Release* equals the published release; source as-of date, warehouse
   publication time (UTC) and import time (UTC) are labelled; mapping coverage and rejected rows are visible.
5. Pin the release so retention keeps it: `python -m cohortwarehouse pin --release r0003 --report CohortWarehouse.pbix`
   (unpin the previous one after the new file is saved).
6. Run the ten reconciliation scenarios in `docs/metric-contracts.md` and archive screenshots and the
   Performance Analyzer export under `bi/evidence/`.
7. Exports: aggregate visuals only; include definition version and release id in the exported title/metadata.
