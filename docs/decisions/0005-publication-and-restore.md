# 0005 — Publication by full copy in one transaction; views for stable access; vocabulary by reference

**Status:** accepted · **Date:** 2026-09-17 · **Requirements:** MOD-04, Section 9.4, NFR-09, NFR-10

## Decision
- `publish --validated-run` refuses unless: the run is `validated` (and not validation-only); the candidate
  schemas were last built by that run; the current vocabulary and the build fingerprint (code, seeds, contract)
  are unchanged since validation; blocking quality results are all passes; and the revision is not older than
  the current release (use `restore` to go back).
- In **one** PostgreSQL transaction: create `star_rNNNN`/`omop_rNNNN`/`bi_rNNNN`; copy star and BI tables with
  `LIKE … INCLUDING ALL`; create OMOP tables from the pinned official DDL (empty CDM tables included) and copy
  populated ones with explicit column lists; compare an order-independent checksum (row count + sum of 60-bit
  row-hash prefixes) for every table; back up the key registry; stamp `bi_release_status`; grant readers; drop
  and recreate every stable view in `star`, `omop`, `bi`; move `ops.current_release`. Any error rolls back all of
  it — schemas, views and pointers (PostgreSQL DDL is transactional).
- OMOP vocabulary tables are **not** copied per release (Athena packages are large). `omop.concept` etc. are
  views over `vocab.*`; each release records its vocabulary version and publication refuses if the loaded
  vocabulary changed since validation. Replacing the vocabulary is therefore a deliberate operation followed by a
  full rebuild and republication.
- `restore --release` verifies the release's recorded checksums, switches views and pointer atomically, then
  rechecks cohort totals through the stable views.

## Consequences
- Publication copying is a full copy (intentional local-scale simplification, included in runtime budgets).
- Power BI must import from an immutable `bi_rNNNN` schema (report parameter), never the moving `bi` views, so
  that separate import queries cannot mix releases.
- Failure drills: `CW_INJECT_PUBLISH_FAILURE=after_copy|before_commit` (tests only).
