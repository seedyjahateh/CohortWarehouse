# 0007 — Resolve each patient's effective batch once; materialise staging

**Status:** accepted · **Date:** 2026-09-17 · **Requirements:** Section 9.1/9.2, NFR-01/02
**Deviation from PRD:** Section 9.1 says "staging uses views".

## Problem (measured, not theorised)
Revision selection originally lived inside each staging view:

```sql
where r._batch_id = coalesce(scoped.batch_id, rev.full_batch_id)
```

PostgreSQL cannot estimate that correlated predicate. It assumed **one row** per staging view, so joining two
staging views produced nested loops: at 1,183-person scale `int_encounters` (1,297 patients × 87,672
encounters) ran for more than ten minutes at 100% CPU before being cancelled. The fixture (25 people) hid the
problem completely — the same plan shape is merely fast on tiny data.

## Decision
1. `stg_ops__relevant_batch` (table) lists the batches contributing to the revision.
2. `stg_ops__effective_patient_batch` (table, unique on `patient_id`) resolves each referenced patient —
   including orphan references and scoped people with no rows — to exactly one batch.
3. `snapshot_rows()` equi-joins that table (`eff.patient_id = r.<patient> and eff.batch_id = r._batch_id`),
   so both sides have real statistics.
4. Synthea staging models are **tables** with indexes on the join and filter columns rather than views, and
   every materialised model runs `ANALYZE` in a post-hook.
5. `ops.entity_key_map` is analysed through `ops.analyze_key_registry()` (SECURITY DEFINER, granted to the
   transformer) right after the registration pre-hooks, because a freshly grown registry otherwise looks
   empty to the planner.

## Consequences
- Staging costs one materialisation pass per run over the selected revision. The PRD already accepts scanning
  source snapshots; the cost is included in the measured runtime.
- Downstream models keep their changed-person incremental behaviour, now with indexed staging tables to probe.
- Lesson recorded in `docs/benchmark.md`: fixture-scale timings cannot validate plan shapes. Every
  performance claim in this project comes from the 1,183-person benchmark, not from the 25-person fixture.
