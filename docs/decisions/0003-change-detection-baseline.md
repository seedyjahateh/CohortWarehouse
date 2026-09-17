# 0003 — Change detection compares against the last BUILT candidate, plus pending people

**Status:** accepted · **Date:** 2026-09-17 · **Requirements:** Section 9.2 steps 2, 6, 8; US-07
**Deviation from PRD:** Section 9.2.2 says to compare against the *published* source state.

## Problem
Candidate schemas are persistent incremental tables. If a run for revision B builds candidates but is never
published (quality failure, operator choice), and the next delivery C reverts a person to their A state, then:
- comparing C with the **published** state (A) says "unchanged", but the candidate tables hold B → stale slice.
- a run that fails half-way leaves some models rewritten for changed people and others not; comparing the next
  delivery with any fingerprint table alone can miss people whose fingerprints happen to match again.

## Decision
- `ops.person_state_built` stores each person's fingerprint as of the last **fully successful** candidate build.
- `int_changed_person` = (current fingerprints ⊖ built fingerprints) ∪ `ops.pending_person`.
- A post-hook on `int_changed_person` records the set in `ops.pending_person` *before* any slice is rewritten.
  `record_built_state` updates built fingerprints and clears pending people only after every stage succeeded.
- Publication advances nothing about change detection; it only copies validated candidates.

## Verified by
`tests/integration/test_fixture_lifecycle.py::test_05` injects a failure in `fct_observation` during the B run
(the failing model's delete+insert rolls back as one transaction, while earlier models already hold B slices)
and `test_06` proves the retry is incremental, reprocesses exactly the pending people and matches expectations.
