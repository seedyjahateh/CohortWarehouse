# 0002 — Persistent key registry and content-based event identity

**Status:** accepted · **Date:** 2026-09-17 · **Requirements:** Section 8.4, NFR-03, US-07

## Decision
- `ops.entity_key_map(entity_type, dataset_id, natural_key) → surrogate_id` allocated from one integer
  sequence (OMOP ids are `integer`). Key `0` is reserved (check constraint) for Unknown star members.
- Registration happens in `int_key_registry` pre-hooks with `INSERT … WHERE NOT EXISTS … ON CONFLICT DO NOTHING`
  so already-registered keys never consume sequence values. Only changed people's events are registered.
- Patients, encounters and organizations use their source UUIDs as natural keys. Conditions, medications and
  observations have no durable source id: natural key = `sha256-canonical-v1` row fingerprint + `:` +
  occurrence ordinal (partitioned by dataset, patient and fingerprint). Identical rows keep their multiplicity.
- The canonical serialisation (`cohortwarehouse/fingerprint.py`) is computed once, at load, by the Python
  loader and stored in `raw.*._row_fingerprint`. A singular test checks across every raw batch that a reused
  fingerprint always has identical content (collision detection).
- OMOP clinical row ids are registered per (source event key, destination table, target concept, mapping
  ordinal). A mapping revision may change them; person ids never change. Star and OMOP share patient and
  encounter ids.
- Every release carries `star_rNNNN._key_registry_backup` (Section 8.4.8).

## Consequences / limitations
- A correction to a keyless row (e.g. P13's systolic 140 → 141) removes the old identity and creates a new one;
  there is no durable source id to preserve. This is disclosed, not hidden.
- Changing the canonical format or the loaded column list of a file changes every event identity for that file
  and must be treated as a full rebuild with a new registry namespace.
- Rebuilding without the registry reproduces clinical content and memberships by source keys, but numeric ids
  differ unless the registry is restored from a release backup.
