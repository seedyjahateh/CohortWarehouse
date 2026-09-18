# Scoped OMOP CDM 5.4 mart

This is a **scoped OMOP CDM 5.4 mart** built from synthetic Synthea CSV exports. It is not a complete OMOP
implementation and has not been assessed for OHDSI network-study readiness. Structure comes from the pinned
official PostgreSQL DDL (`sql/omop/OMOPCDM_postgresql_5.4_ddl.sql`, OHDSI/CommonDataModel `v5.4.2`,
SHA-256 `ae99be6e…c4771`, verified at load).

## Table categories (GOV-02)

| Category | Tables | Meaning |
|---|---|---|
| Populated and tested | PERSON, OBSERVATION_PERIOD, VISIT_OCCURRENCE, CONDITION_OCCURRENCE, DRUG_EXPOSURE, MEASUREMENT, OBSERVATION, DEATH, CDM_SOURCE | Built by dbt, column set/types compared with the official DDL, keys/relationships/concepts tested, cohort reconciliation run against them |
| Vocabulary (by reference) | CONCEPT, VOCABULARY, DOMAIN, CONCEPT_CLASS, RELATIONSHIP, CONCEPT_RELATIONSHIP (+ CONCEPT_ANCESTOR, CONCEPT_SYNONYM, DRUG_STRENGTH when supplied) | Loaded from an Athena package into `vocab`; `omop.*` views point to it; version recorded per release |
| Structurally present, empty | every other CDM 5.4 clinical/health-system/derived table (e.g. PROCEDURE_OCCURRENCE, DEVICE_EXPOSURE, VISIT_DETAIL, NOTE, SPECIMEN, LOCATION, CARE_SITE, PROVIDER, PAYER_PLAN_PERIOD, COST, DRUG_ERA, CONDITION_ERA, EPISODE, METADATA, FACT_RELATIONSHIP) | Created from the official DDL in each `omop_rNNNN`; no data, no tests. CARE_SITE/PROVIDER/PROCEDURE are P1 |
| Project extensions (not CDM) | `cw_event_crosswalk`, `cw_exclusion_ledger` | Source-to-row lineage, imputation flags and exclusions. Custom fields never appear inside CDM tables |

## Population and inferred periods
- A person is in PERSON only if they have at least one supported event (visit or routed clinical row) on or
  before min(D, death date). Others are listed in `cw_exclusion_ledger` (`omop_person`) and remain in the star.
- OBSERVATION_PERIOD is **one inferred span** per person: earliest supported event → latest supported boundary,
  clipped to D and death. It does not establish continuous coverage or enrolment. `observation_period_id = person_id`.
- Events after D stay in the event tables (outside the inferred period) and are profiled in `bi_data_profile`.

## ETL conventions and imputations
| Field | Rule |
|---|---|
| `visit_end_date` (required) | encounter STOP date; START date when STOP is absent (`cw_event_crosswalk.end_date_imputed`) |
| `drug_exposure_end_date` (required) | STOP date; START date when absent **or impossible** (flagged). `verbatim_end_date` keeps the supplied value only when it is usable |
| Impossible STOP (earlier than START) | Source defect (Synthea v3.3.0 medications: 108 of 77,303 rows at 1,183-person scale). The event is kept; the unusable end value is nulled and preserved as `source_stop_value` with `stop_status = stop_before_start_nulled`; the row is listed in `cw_exclusion_ledger` (`data_quality`, `event_retained = true`) and counted in `bi_data_profile`. The star carries no end date (date key 0); OMOP imputes from the start date |
| `quantity`, `days_supply`, `refills`, `route`, `sig` | null — Synthea dispenses are not individual fills; nothing is inferred |
| `*_type_concept_id` | Type Concept `OMOP4976890` (EHR), resolved by code from the loaded vocabulary |
| `birth_datetime`, `death_datetime`, condition datetimes | null — source supplies dates only |
| `person_source_value` | pseudonymous id, never the source UUID |
| `care_site_id`, `provider_id`, `location_id` | null (P1) |
| `unit_concept_id` | null when no unit supplied; 0 when supplied but not in the unit policy / vocabulary |
| `value_as_concept_id` | populated from a valid `Maps to value` relationship (observation/measurement only) |
| Visit concepts | `dbt/seeds/encounter_classes.csv` (review_status `not_reviewed`); home, virtual, hospice, snf → 0 |

## Mapping (MAP-01..06)
Source vocabulary normalised through `source_vocabulary_aliases` (SNOMED for conditions, RxNorm for
medications, LOINC for observations when no system column exists). A valid standard source concept is used
directly; otherwise valid `Maps to` relationships to valid standard concepts. Routing is by **target domain**
(Condition, Drug, Measurement, Observation); other domains, ambiguous unmapped events and unsupported
`Maps to value` cases enter the exclusion ledger. Unmapped events are kept with concept 0 only where the
source contract makes the domain defensible (`unmapped_routing` seed). Coverage — event-weighted and
distinct-code, with denominators and exceptions — is published in `bi_mapping_coverage`; cohort codes must be
100% mapped, each input file ≥ 95% event-weighted.

**Coverage categories:** input files (conditions, medications, observations). `observations.csv` feeds both
MEASUREMENT and OBSERVATION by target domain, so it is assessed as one input category.

## Known limitations
- Verified so far only with the **fictional** test vocabulary; real-vocabulary release validation is outstanding
  (see `docs/decisions/0006`).
- No descendant expansion, eras, CONCEPT_ANCESTOR use or DRUG_STRENGTH (P1).
- Achilles/DataQualityDashboard have not been run; `bi_data_profile` is an Achilles-style descriptive profile.
- Encounter class → visit mappings and demographic mappings are unreviewed demonstration choices.
