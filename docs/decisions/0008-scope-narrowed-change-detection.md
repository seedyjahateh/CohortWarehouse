# 0008 — Narrow change detection and staging to the delivered scope

**Status:** accepted · **Date:** 2026-09-18 · **Requirements:** NFR-02, Section 9.2

## Problem (measured)
The first incremental run of a delivery changing 5% of the benchmark population (65 of 1,183 people) took
**620 s**, against NFR-02's 5-minute budget. The profile showed the work was not proportional to the change:

| Node | Seconds | Why |
|---|---|---|
| `int_observations` | 55.3 | changed-person filter is a **semi-join**, which PostgreSQL cannot push through the occurrence-ordinal window, so the window was recomputed over all 1.13M rows |
| `stg_synthea__observations` | 39.8 | staging re-materialised the whole snapshot every run |
| `int_person_fingerprint` | 14.6 | every person was re-hashed to find the 65 that changed |

## Decision
1. **Occurrence ordinals move into staging.** The window is evaluated once per run where the rows are
   materialised; intermediate person slices then filter by an indexed `patient_id` lookup.
2. **Staging models become change-candidate slices** (`incremental` + transactional delete of the candidate
   slice), like the intermediate and mart layers.
3. **`stg_ops__change_candidate`** defines the candidate set: patients named by the scope of every delivery
   since the last successful build, plus `ops.pending_person`. Only those can differ, because absent rows are
   removals *only* within a declared replacement scope (Section 9.2.3).
4. The narrowing is **abandoned whenever it cannot be proven safe** — full refresh, no previous build, a full
   snapshot among the new deliveries, or a target revision at/behind the built one. Then every referenced
   patient is a candidate and behaviour is identical to before.
5. `int_person_fingerprint` and the built-state comparison in `int_changed_person` are both restricted to
   candidates (restricting only one side would report every other person as removed).

## Safety
- `assert_incremental_slices_match_source` now also compares **staging against the raw snapshot** by multiset
  counts per person and content fingerprint, so a stale or missing staging slice fails the gate on every build.
- The A→B→C fixture drills still assert exact cohort membership, key stability, replay with zero changes and
  incremental-equals-full-rebuild.
