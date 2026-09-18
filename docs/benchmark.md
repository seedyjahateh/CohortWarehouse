# Benchmark: measured results

> Every number here was measured on the hardware and software described below. Nothing is extrapolated.
> Where a target was **not** met, or could not be measured, that is stated plainly.
> Synthetic data — demonstration only.

## Environment (measured 2026-09-17/18)

| Item | Value |
|---|---|
| Host | Windows 11 Pro 26100, 12 logical CPUs, 15.7 GB RAM, SSD |
| Container runtime | Docker Desktop 29.7.2 (WSL2), ~7.6 GB available to containers |
| Warehouse | PostgreSQL 16.10 (pinned digest); `shared_buffers=512MB`, `work_mem=96MB`, `maintenance_work_mem=512MB`, `max_wal_size=2GB`, `shm_size=1GB`, `timezone=UTC` |
| Transform | dbt-core 1.12.5 / dbt-postgres 1.11.0, **2 threads** (`CW_DBT_THREADS=2`) |
| Generator | Synthea v3.3.0 jar (SHA-256 verified) in `eclipse-temurin:17.0.16_8-jre-jammy` (pinned digest), 3 GB heap |
| Vocabulary | **FICTIONAL test vocabulary** (`CW-TEST-FICTIONAL-2026.09`) |
| Free disk | 9–22 GB during the measurements (the PRD reference machine specifies 30 GB — see "Environment limits") |
| Other load | An unrelated container (`reprohpc-lab`, another project on this laptop) was running during part of the measurements. Where it changed a result, both figures are given. |

This host is **below** the PRD reference machine and was not quiet. Treat these figures as a lower bound.

## Dataset (release benchmark)

`config/demo.yml`: Synthea v3.3.0, seed 20260915, clinician seed 20260915, Massachusetts, **1,000 requested**
patients, reference **and** end date 2026-06-30, 10 years of history.

| Source file | Accepted records | Quarantined |
|---|---|---|
| patients | 1,183 | 0 |
| encounters | 87,077 | 0 |
| conditions | 46,751 | 0 |
| medications | 76,773 | 0 |
| observations | 1,131,667 | 0 |
| organizations | 834 | 0 |
| **total** | **1,344,285** | **0** |

1,183 people for 1,000 requested: the requested population counts living people and 183 died during the
simulation (`generate.only_alive_patients=false`). The actual count is recorded, never assumed. This delivery
also satisfies the P1 scale threshold of ≥ 1 million supported event rows.

**Generation:** 493 s (8 min 13 s) wall clock in the pinned container.
**Reproducibility (ING-01):** verified — `docs/evidence/generation-reproducibility.md`.

## Raw load (ING-04/06)

Per-file loader timings (`ops.batch_file.load_seconds`), whole batch in one transaction, all rows validated
and fingerprinted in Python before COPY:

| File | Rows | Seconds (loaded host) | Seconds (quiet host) |
|---|---|---|---|
| observations | 1,131,667 | 298.2 | — |
| encounters | 87,077 | 23.5 | — |
| medications | 76,773 | 12.5 | — |
| conditions | 46,751 | 8.0 | — |
| patients | 1,183 | 1.1 | — |
| organizations | 834 | 0.2 | — |
| **total batch** | **1,344,285** | **343.5 (3,914 rows/s)** | **77.9 (17,257 rows/s)** |

The same batch was loaded twice: once while another container was competing for CPU/IO (343 s) and once on a
quiet host (78 s). Raw-load throughput is accepted source rows ÷ loader elapsed seconds; it is never mixed
with end-to-end throughput. The incremental delivery (62,027 rows) loaded in 8.6 s.

## Full refresh of the whole benchmark

| Measurement | staging+intermediate | star+OMOP | BI | quality gate | total |
|---|---|---|---|---|---|
| First attempt (cold key registry, loaded host, pre-optimisation) | 2,067 s | 114 s | 32 s | ~273 s | **2,486 s (41 min)** |
| Warm key registry, pre-optimisation | 456 s | 183 s | 28 s | ~308 s | **975 s (16 min)** |
| **After the optimisations below (warm registry)** | **289 s** | **133 s** | **33 s** | **~62 s** | **542 s (9 min)** |

The first-ever build is much slower than later ones because it allocates ~2.25M surrogate keys in the
registry; subsequent builds find them already registered.

## Publication, restore and NFR-01 (load → publication ≤ 20 min)

| Step | Measured | Conditions |
|---|---|---|
| Raw load of the batch | 78 s | quiet host |
| Full refresh build + quality gate | 542 s | 2 dbt threads, warm registry, quiet host |
| **Publication of the release** (30 tables: full copy, per-table checksums, atomic view switch, all in one transaction) | **139 s** | 2 threads, quiet host |
| **Composite load → publication** | **759 s (12 min 39 s)** | **inside the 20-minute budget** |
| Same pipeline, 1 dbt thread while the host had ~0.5 GB free RAM | build+gate 1,378 s, publish 663 s, total 2,041 s (34 min) | **outside the budget** |
| Restore of the previous release (checksum verification of 30 tables + view switch + cohort recheck) | **62 s** (and 53 s to switch back) | **NFR-10 met** (budget 15 min) |

**NFR-01 status: met on this host only under adequate conditions, and not yet as three consecutive runs.**
The 759 s figure is the sum of separately measured steps on the same pinned revision (load, then
build+gate, then publish), each observed directly. One *continuous* run measured end to end took 34 minutes
because the host had ~0.5 GB free RAM and one dbt thread. Two attempts to run three consecutive measured
runs were killed by the host's memory manager. The honest conclusion: the pipeline fits the budget with two
dbt threads on a machine that meets the PRD's reference specification, and this laptop does not reliably
meet it while also holding a 1.34M-row warehouse.

Publication here is a **fixture-profile** release: it is recorded in `ops.release.validation_profile` as
`fixture` because the loaded vocabulary is the fictional test package. Only the `release` profile, with a
pinned real vocabulary, can certify a release.

## Incremental run — NFR-02 (≤ 5 minutes for a batch changing 5% of patients)

Derived scoped delivery (`scripts/make_incremental_delivery.py`) changing **65 of 1,183 people (5.0%)**:
24 late arrivals, 18 keyless corrections, 12 people with all events removed, 5 people removed entirely,
6 new people. Change detection found exactly `{new: 6, changed: 54, removed: 5}`.

| Measurement | staging+intermediate | star+OMOP | BI | quality gate | total |
|---|---|---|---|---|---|
| Before optimisation | 242 s | 72 s | 20 s | ~280 s | 620 s (10 min) |
| **After optimisation** | **79 s** | **57 s** | **15 s** | **~62 s** | **214 s (3 min 34 s)** |

**NFR-02 build + gate: met** (214 s of a 300 s budget). Publication is not included because the gate
correctly refuses this delivery (fictional vocabulary, below); the release copy of ~1.3M rows is therefore
unmeasured, and NFR-02 cannot be closed end to end until a real vocabulary is loaded.

### What the optimisations were (all driven by measurement, ADRs 0007 and 0008)
1. **Planner-friendly revision selection.** The correlated `coalesce()` batch predicate made PostgreSQL
   estimate one row per staging view, producing nested loops between views: `int_encounters` ran 1,297
   patients × 87,672 encounters for >10 minutes before being cancelled. Each patient's effective batch is now
   resolved once into an indexed table.
2. **Occurrence ordinals in staging.** The changed-person filter is a semi-join, which cannot be pushed
   through a window function, so `int_observations` recomputed its window over all 1.13M rows (55 s) to
   process 65 people. Moving the ordinal into staging made that slice an indexed lookup.
3. **Scope-narrowed change detection.** Only people named by a scoped delivery can change, so staging and
   fingerprinting are limited to that set — with a fallback to the whole population whenever narrowing is not
   provably safe.
4. **Aggregate-based consistency checking.** `assert_incremental_slices_match_source` compared multiset
   EXCEPTs over 1.34M-row sets (247 s of a 272 s gate). It now compares per-layer row counts and
   order-independent content digests in one pass per layer — same strength, ~8 s — and additionally compares
   **staging against the raw snapshot**, which the earlier version did not.
5. **Fingerprint collision check in two passes**: find repeating fingerprints first, compare canonical
   content only inside those groups (68 s → seconds).

The remaining full-refresh cost is dominated by materialising and indexing the observation-shaped models
(1.13M rows each, several times along `raw → staging → intermediate → star/OMOP`). Removing those redundant
materialisations is the next performance item and is **not** implemented.

## Quality gate at benchmark scale

All **275 dbt tests pass** on the 1.34M-row delivery: keys, relationships, temporal rules, conservation,
source-to-target accounting, OMOP concept validity, the official-DDL column contract, cohort equality against
independent SQL and against the OMOP mart, and the staging/intermediate/star/candidate consistency digests.

Three coverage checks do not meet their thresholds — conditions 11.5%, medications 13.5%, observations 7.5%
event-weighted (cohort code sets 100%) — because the loaded vocabulary is the **fictional test package**,
which maps only a handful of codes. Under the `fixture` validation profile these are recorded as **warnings**
(the percentages describe the test vocabulary, not the ETL), so the full path including publication can be
exercised and measured. Under the `release` profile they are **blocking**, and that profile additionally
refuses a test-only vocabulary outright. Every release records which profile validated it.

## Environment limits encountered (worth recording)

* The first benchmark attempt filled the disk (0 bytes free), which wedged the Docker daemon and required
  restarting Docker Desktop and the WSL VM. The PRD's 30 GB requirement is real; the README now says so.
* Docker's default 64 MB `/dev/shm` made a gate test fail while resizing a shared-memory segment at 1.34M
  rows. `compose.yml` now sets `shm_size: 1gb`.
* A 10 s `connect_timeout` was too tight while the warehouse was saturated and failed a benchmark stage
  mid-run; it is now 60 s by default.
* Host contention changes results by 3–4× (see the load table). Timings here are reported with their conditions.

## Still to measure

| Target | Status |
|---|---|
| NFR-01 ≤ 20 min load → publication, 3 runs | **partially met**: 759 s composite (load 78 s + build/gate 542 s + publish 139 s) with 2 threads on a quiet host; 2,041 s in one continuous run on a memory-starved host; 3 consecutive runs not completed (host memory) |
| NFR-02 ≤ 5 min for a 5% change | **met for build + gate** (214 s); publication of a 5% change not separately measured |
| NFR-10 restore ≤ 15 min | **met at benchmark scale**: 62 s including checksum verification of 30 tables |
| NFR-07 BI p95 visual ≤ 2 s / page ≤ 5 s | **not started**: needs the Power BI report |
| NFR-08 SQL cohort p95 ≤ 2 s over ≥ 20 runs with plans | **met**: p95 2.2–16.4 ms across six reference queries, 25 warm runs each, plans archived (`docs/evidence/sql-latency.md`) |
| NFR-04 ten scheduled runs meeting 06:00 UTC | **not started**: needs a live Airflow deployment |
