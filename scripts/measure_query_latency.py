"""Measure reference cohort-query latency (NFR-08) and archive PostgreSQL execution plans.

    python scripts/measure_query_latency.py [--runs 25] [--schema-bi work_bi] [--schema-star work_star]

Reports the first (cold) execution separately from warm-cache runs, as the PRD requires, and writes
`artifacts/latency/<timestamp>.json` plus the EXPLAIN (ANALYZE, BUFFERS) text of every query.

By default it measures the candidate schemas (`work_bi`, `work_star`). Point it at a published release
(`--schema-bi bi_r0003 --schema-star star_r0003`) once a release exists.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cohortwarehouse.db import connect  # noqa: E402
from cohortwarehouse.settings import load_dotenv, repo_root  # noqa: E402

QUERIES: dict[str, str] = {
    # What the Cohort discovery page asks: cohort counts and share of the eligible denominator.
    "cohort_counts_and_share": """
        select d.cohort_id, d.cohort_label,
               count(distinct m.patient_key) as cohort_patients,
               (select count(*) from {bi}.bi_patient_snapshot) as eligible_patients,
               round(100.0 * count(distinct m.patient_key)
                     / nullif((select count(*) from {bi}.bi_patient_snapshot), 0), 2) as cohort_share_pct
        from {bi}.bi_cohort_definition d
        left join {bi}.bi_cohort_membership m on m.cohort_id = d.cohort_id
        group by d.cohort_id, d.cohort_label
        order by d.cohort_id
    """,
    # Demographic breakdown of one cohort under a filter, as the slicers produce.
    "cohort_demographics_filtered": """
        select s.age_band, s.recorded_sex, count(*) as patients
        from {bi}.bi_cohort_membership m
        join {bi}.bi_patient_snapshot s using (patient_key)
        where m.cohort_id = 'C2' and s.race = 'white'
        group by s.age_band, s.recorded_sex
        order by s.age_band, s.recorded_sex
    """,
    # Monthly utilisation trend for one cohort (pre-aggregated month table).
    "cohort_monthly_trend": """
        select mo.month_start_date, sum(c.encounter_count) as encounters,
               count(distinct c.patient_key) as patients
        from {bi}.bi_cohort_month c
        join {bi}.bi_month mo using (month_key)
        where c.cohort_id = 'C3'
        group by mo.month_start_date
        order by mo.month_start_date
    """,
    # Evidence drill-through for a cohort member sample.
    "member_evidence_sample": """
        select e.cohort_id, e.evidence_type, count(*) as evidence_rows,
               count(distinct e.patient_key) as patients
        from {bi}.bi_member_evidence e
        where e.cohort_id = 'C1'
        group by e.cohort_id, e.evidence_type
        order by 2
    """,
    # The same population computed from the star schema, as a reviewer would check it.
    "star_hypertension_population": """
        select count(distinct f.patient_key) as patients, count(*) as condition_rows
        from {star}.fct_condition f
        join {star}.dim_clinical_code c using (clinical_code_key)
        join {star}.dim_date d on d.date_key = f.start_date_key
        where c.source_code in ('59621000', '38341003')
          and c.source_vocabulary_id = 'SNOMED'
          and d.full_date <= date '2026-06-30'
          and (f.end_date is null or f.end_date >= date '2026-06-30')
    """,
    # Utilisation from the star: distinct encounters in the 365-day window.
    "star_window_encounters": """
        select count(distinct f.encounter_key) as encounters, count(distinct f.patient_key) as patients
        from {star}.fct_encounter f
        where f.start_date between date '2026-06-30' - 364 and date '2026-06-30'
    """,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=int, default=25, help="warm executions per query (>= 20 for NFR-08)")
    parser.add_argument("--schema-bi", default="work_bi")
    parser.add_argument("--schema-star", default="work_star")
    parser.add_argument("--role", default="transformer")
    args = parser.parse_args(argv)
    load_dotenv()

    results = {}
    plans = {}
    with connect(args.role) as conn:
        with conn.cursor() as cur:
            cur.execute(f"select count(*) from {args.schema_bi}.bi_patient_snapshot")
            eligible = cur.fetchone()[0]
        for name, template in QUERIES.items():
            sql = template.format(bi=args.schema_bi, star=args.schema_star)
            with conn.cursor() as cur:
                started = time.perf_counter()
                cur.execute(sql)
                rows = cur.fetchall()
                cold_ms = (time.perf_counter() - started) * 1000

                warm: list[float] = []
                for _ in range(args.runs):
                    started = time.perf_counter()
                    cur.execute(sql)
                    cur.fetchall()
                    warm.append((time.perf_counter() - started) * 1000)

                cur.execute("explain (analyze, buffers, verbose off) " + sql)
                plans[name] = "\n".join(line[0] for line in cur.fetchall())
            ordered = sorted(warm)
            index95 = max(0, int(round(0.95 * len(ordered))) - 1)
            results[name] = {
                "result_rows": len(rows),
                "cold_ms": round(cold_ms, 1),
                "warm_runs": len(warm),
                "min_ms": round(ordered[0], 1),
                "median_ms": round(statistics.median(ordered), 1),
                "p95_ms": round(ordered[index95], 1),
                "max_ms": round(ordered[-1], 1),
                "meets_2s_p95": ordered[index95] <= 2000,
            }
            print(f"{name:34} p95 {results[name]['p95_ms']:8.1f} ms  (cold {results[name]['cold_ms']:.0f} ms)")
        conn.rollback()

    directory = repo_root() / "artifacts" / "latency"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    report = {
        "measured_at_utc": stamp,
        "schemas": {"bi": args.schema_bi, "star": args.schema_star},
        "eligible_patients": eligible,
        "warm_runs_per_query": args.runs,
        "target_p95_ms": 2000,
        "queries": results,
        "all_meet_target": all(q["meets_2s_p95"] for q in results.values()),
    }
    (directory / f"{stamp}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (directory / f"{stamp}-plans.txt").write_text(
        "\n\n".join(f"=== {name} ===\n{plan}" for name, plan in plans.items()), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("eligible_patients", "all_meet_target")}, indent=2))
    print(f"report: {directory / (stamp + '.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
