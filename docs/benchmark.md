# Benchmark: measured results

> Every number here was measured on the hardware and software described below. Nothing is extrapolated.
> Where a target was **not** met, that is stated plainly. Synthetic data — demonstration only.

## Environment (as measured, 2026-09-17/18)

| Item | Value |
|---|---|
| Host | Windows 11 Pro 26100, 12 logical CPUs, 15.7 GB RAM, SSD |
| Container runtime | Docker Desktop 29.7.2 (WSL2), ~7.6 GB available to containers |
| Warehouse | PostgreSQL 16.10 (pinned digest); `shared_buffers=512MB`, `work_mem=96MB`, `maintenance_work_mem=512MB`, `max_wal_size=2GB`, `shm_size=1GB`, `timezone=UTC` |
| Transform | dbt-core 1.12.5 / dbt-postgres 1.11.0, **2 threads** (`CW_DBT_THREADS=2`) |
| Generator | Synthea v3.3.0 jar (SHA-256 verified) in `eclipse-temurin:17.0.16_8-jre-jammy` (pinned digest), 3 GB heap |
| Vocabulary | **FICTIONAL test vocabulary** (`CW-TEST-FICTIONAL-2026.09`) |
| Free disk at start | ~9–10 GB (the PRD's reference machine specifies 30 GB; see "Environment limits" below) |
| Concurrency | An unrelated container (`reprohpc-lab`, another project on this laptop) was running and consuming CPU/RAM during the measured runs |

This is **below** the PRD reference machine (which assumes 30 GB free working space and a quiet host). Treat
these figures as a lower bound for a dedicated machine, not as the project's best achievable performance.

## Dataset (release benchmark)

`config/demo.yml`: Synthea v3.3.0, seed 20260915, clinician seed 20260915, Massachusetts, **1,000 requested**
patients, reference and end date 2026-06-30, 10 years of history.

| Source file | Accepted records | Quarantined |
|---|---|---|
| patients | 1,183 | 0 |
| encounters | 87,077 | 0 |
| conditions | 46,751 | 0 |
| medications | 76,773 | 0 |
| observations | 1,131,667 | 0 |
| organizations | 834 | 0 |
| **total** | **1,344,285** | **0** |

1,183 people were generated for 1,000 requested: the requested population counts living people, and 183 died
during the simulation (`generate.only_alive_patients=false`). The actual count is recorded, never assumed.
This delivery also satisfies the P1 scale threshold of ≥ 1 million supported event rows.

**Generation:** 493 s (8 min 13 s) wall clock in the pinned container.
**Reproducibility:** see `docs/evidence/generation-reproducibility.md` — identical clinical content across two
runs once the end date is pinned; record order is documented volatile metadata.

## Raw load (ING-04/06)

Measured per file by the loader (`ops.batch_file.load_seconds`), one transaction for the whole batch:

| File | Rows | Seconds | Rows/s |
|---|---|---|---|
| observations | 1,131,667 | 298.2 | 3,795 |
| encounters | 87,077 | 23.5 | 3,704 |
| medications | 76,773 | 12.5 | 6,150 |
| conditions | 46,751 | 8.0 | 5,873 |
| patients | 1,183 | 1.1 | 1,099 |
| organizations | 834 | 0.2 | 3,432 |
| **total** | **1,344,285** | **343.5** | **3,914** |

Raw-load throughput is accepted source rows ÷ loader elapsed seconds and is **not** mixed with end-to-end
throughput. Every row is validated in Python (contract types, scope, duplicate natural keys) and fingerprinted
before COPY, which is where the per-row cost sits.

## Full-refresh build and quality gate

First measured full refresh of the 1.34M-row delivery (`run --full-refresh`, then the gate):

| Stage | Seconds |
|---|---|
| dbt build: staging + intermediate | 2,067 |
| dbt build: star + OMOP | 114 |
| dbt build: BI | 32 |
| quality gate (full `dbt test` + Python checks) | ~273 |
| **build + gate total** | **2,486 (41 min)** |

**NFR-01 (≤ 20 minutes from load through publication) is NOT met on this host.** Reported honestly rather
than adjusted. What the measurement shows:

* The staging + intermediate stage is ~83% of the time, and inside it the cost is dominated by materialising
  and indexing the observation-shaped models (1.13M rows each) and registering ~2.25M surrogate keys.
* The same 1.13M rows are currently materialised several times along the path
  `raw → stg_synthea__observations → int_observations → fct_observation` and
  `→ int_omop_event_candidates → int_omop_events → measurement/observation`.
* The obvious next optimisation is to remove redundant materialisations (build star facts directly from
  staging, and keep one routed-event table instead of candidates plus events). That is **not** implemented
  yet; it is the top performance item in the roadmap.
* Slower than an earlier partial measurement of the same stage (925 s) because the host was also running an
  unrelated container; host contention is disclosed rather than filtered out.

**Publication was not measured end to end**, because the gate correctly refuses to publish this delivery: the
loaded vocabulary is the fictional test package, so mapping coverage is far below the required thresholds
(conditions 11.5%, medications 13.5%, observations 7.5% event-weighted; cohort code sets 100%). NFR-01 covers
load *through publication*, so it cannot be closed until a real OHDSI vocabulary is loaded.

For reference, publication of the 25-person fixture (30 tables, full copy + checksums + view switch) takes
1.3 s, and restore takes well under a second — both far inside their budgets, but at fixture scale.

## Environment limits encountered (worth recording)

* The first attempt at this benchmark filled the disk (0 bytes free), which wedged the Docker daemon and
  required restarting Docker Desktop and the WSL VM. The PRD's 30 GB requirement is real; the README now says so.
* Docker's default 64 MB `/dev/shm` made a gate test fail while resizing a shared-memory segment at 1.3M rows.
  `compose.yml` now sets `shm_size: 1gb`.
* `connect_timeout` of 10 s was too tight while the warehouse was saturated and failed a benchmark stage
  mid-run; it is now 60 s by default.

## Still to measure

| Target | Status |
|---|---|
| NFR-01 ≤ 20 min load → publication, 3 runs | **not met / incomplete**: 1 run measured at 41 min for build+gate; publication blocked by the vocabulary gate |
| NFR-02 ≤ 5 min for a batch changing 5% of people | **not yet measured**: `scripts/make_incremental_delivery.py` produces the delivery; the run has not been executed |
| NFR-07 BI p95 visual ≤ 2 s / page ≤ 5 s | **not started**: needs the Power BI report |
| NFR-08 SQL cohort p95 ≤ 2 s over ≥ 20 runs with plans | **not started** |
| NFR-04 ten scheduled runs meeting 06:00 UTC | **not started**: needs a live Airflow deployment |
| Recovery ≤ 15 min at benchmark scale | measured only at fixture scale (automated drill) |
