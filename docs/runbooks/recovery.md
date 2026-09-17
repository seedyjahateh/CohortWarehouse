# Recovery runbook (NFR-10: prior release restored and verified ≤ 15 minutes)

## Restore a previous release
```powershell
python -m cohortwarehouse releases --dataset-id <dataset>          # find current / previous / pinned
python -m cohortwarehouse validate --release r0002                 # checksum verification, read-only
python -m cohortwarehouse restore  --release r0002 --reason "bad release r0003"
```
`restore` re-verifies every table checksum recorded at publication, switches all stable `star`/`omop`/`bi`
views and `ops.current_release` in one transaction, then rechecks cohort totals through the views. Power BI
reports pinned to an immutable `bi_rNNNN` schema are unaffected until their parameter is changed.

Then:
1. Record the reason and timing in `docs/evidence/recovery-drill.md` (commands, start/end time, verification output).
2. If Power BI should show the restored release: set the `ReleaseSchema` parameter to its `bi_rNNNN`, refresh,
   confirm the *Imported Release* card.
3. To return to the intended release later: `restore --release <id>`.

## Key registry recovery
Every release carries `star_rNNNN._key_registry_backup`. If `ops.entity_key_map` is lost or corrupted:
```sql
-- as admin, inside one transaction, after confirming the backup's row count
truncate ops.entity_key_map;
insert into ops.entity_key_map select * from star_r0003._key_registry_backup;
select setval('ops.entity_key_seq', (select max(surrogate_id) from ops.entity_key_map));
```
Then rebuild with `run --full-refresh`. Without a backup, a rebuild reproduces clinical content and memberships
by source keys but numeric ids will differ (ADR 0002).

## Drill evidence already automated
`tests/integration/test_fixture_lifecycle.py` exercises: failure mid-model (slice rollback + pending retry),
injected failure inside the publication transaction (nothing changes), restore to the oldest release and back,
and a wrong-person visit link that must block publication.
