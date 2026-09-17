# 0004 — Incremental person slices through the intermediate layer, and when to rebuild fully

**Status:** accepted · **Date:** 2026-09-17 · **Requirements:** MOD-05, Section 9.2, NFR-02/03

## Context
The first implementation kept intermediate models as views. On 25 synthetic people a single star dimension
took 17 s: unanalysed relations under deeply nested views produced nested-loop plans that rescanned view
subtrees hundreds of times — quadratic behaviour that would not survive the 1,000-person benchmark.

## Decision
- Person-linked intermediate models (`int_encounters`, `int_conditions`, `int_medications`, `int_observations`,
  `int_omop_event_candidates`, `int_omop_persons`, `int_omop_events`) and all person-linked star/OMOP models are
  `incremental` + `append` with a transactional pre-hook that deletes the changed people's slice. dbt-postgres
  runs pre-hook, insert and post-hook in one transaction.
- Occurrence-ordinal windows are partitioned by patient, so the changed-person filter pushes below the window.
- Every materialised model runs `ANALYZE` in a post-hook; raw tables are analysed after each load through the
  narrowly scoped `ops.analyze_raw()` security-definer function.
- Small dimensions, BI summaries, concept map, exclusion ledger and person fingerprints are rebuilt per run
  (scanning the snapshot is accepted by the PRD and included in measured runtime).
- **Automatic full refresh** (recorded in `ops.pipeline_run.full_refresh_reason`) when: no previous build; the
  candidate schemas were last written by another dataset (`ops.candidate_owner`, set when a build *starts*);
  transformation code, seeds, source contract or vocabulary version changed (build fingerprint); the as-of
  date changed (eligibility, observation periods); the organization id set changed; the target revision
  precedes the built revision; or the run is validation-only.

## Cross-person staleness guard
An event's encounter link depends on another person's encounter when a wrong-person link exists. Such links are
blocking, and `tests/assert_no_wrong_person_visit_links.sql` recomputes them from the selected revision rather
than from incremental tables, so a change to either person is always caught. `assert_incremental_slices_match_source`
compares every incremental table's identity set with a full recomputation on every build.

## Documented audit differences (NFR-03)
Incremental and full rebuilds must match exactly except: source locators (`source_batch_id`,
`source_record_number` — an unchanged person keeps the locator of the batch that last supplied their rows),
run ids, build/publish timestamps, git sha, delivery revision/timestamps and descriptive delivery text in
`cdm_source`/`bi_release_status`. `tests/integration/test_fixture_lifecycle.py::test_09` enforces this list.
