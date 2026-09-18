# NFR-08 evidence: reference cohort-query latency

**Measured:** 2026-09-18 on the 1,183-person / 1,344,285-row benchmark (see `docs/benchmark.md` for the
environment). Target: p95 ≤ 2 s per reference query, ≥ 20 runs, first (cold) run reported separately.

Command: `python scripts/measure_query_latency.py --runs 25`
Artifacts: `artifacts/latency/<timestamp>.json` and `<timestamp>-plans.txt` (EXPLAIN ANALYZE, BUFFERS).

Measured against the **candidate** schemas (`work_bi`, `work_star`) because publication is blocked by the
fictional-vocabulary coverage gate. The published release schemas are byte-for-byte copies of these tables,
so the plans are representative; the script takes `--schema-bi bi_rNNNN --schema-star star_rNNNN` once a
release exists.

| Reference query | Cold (ms) | Warm median (ms) | **p95 (ms)** | Max (ms) | ≤ 2 s |
|---|---|---|---|---|---|
| Cohort counts and share of eligible | 8 | ~4 | **4.6** | — | yes |
| Cohort demographics under a filter (C2 × race) | 3 | ~2 | **2.2** | — | yes |
| Monthly utilisation trend (C3) | 4 | ~4 | **4.5** | — | yes |
| Member evidence drill-through (C1) | 7 | ~2 | **2.6** | — | yes |
| Hypertension population from the **star** | 12 | ~10 | **10.3** | — | yes |
| 365-day distinct encounters from the **star** | 18 | ~16 | **16.4** | — | yes |

25 warm runs per query. **NFR-08 is met**, with roughly two orders of magnitude of headroom: the BI tables are
pre-aggregated per person and per cohort-month, so the dashboard queries touch hundreds of rows rather than
the 1.13M-row observation fact.

## Population and cohort sizes at benchmark scale

| Figure | Value |
|---|---|
| Accepted source patients | 1,183 |
| Eligible at D = 2026-06-30 (adult, alive, ≥ 1 encounter in [D−364, D]) | 738 |
| C1 recorded hypertension | 334 |
| C2 C1 + latest valid systolic > 140 in [D−89, D] | 11 |
| C3 ≥ 3 distinct encounters in [D−364, D] | 404 |
| OMOP PERSON rows | 1,183 |
| OMOP MEASUREMENT rows | 747,693 |
| Star `fct_observation` rows | 1,131,667 |

C2 is small because the **fictional** vocabulary maps only a handful of codes, so few systolic measurements
carry a valid standard concept, and because Synthea's simulated blood-pressure values rarely exceed 140 in
the 89-day window. These are properties of synthetic data and a test vocabulary, not prevalence estimates.

Mapping coverage on this delivery is far below the release thresholds (conditions 11.5%, medications 13.5%,
observations 7.5%; cohort code sets 100%) precisely because the vocabulary is fictional — the gate refuses to
publish, which is the intended behaviour.
