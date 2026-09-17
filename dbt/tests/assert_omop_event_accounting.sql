-- OMOP accounting (Section 11.3): every routed candidate of an included person appears in exactly one CDM
-- table via the crosswalk, every CDM clinical row has a crosswalk entry, and every candidate that is not in
-- a CDM table is explained by the exclusion ledger. Mapping fan-out is expected, not loss. Zero rows = pass.
with cdm_rows as (
    select 'condition_occurrence' as destination_table, condition_occurrence_id as omop_row_id from {{ ref('omop_condition_occurrence') }}
    union all select 'drug_exposure', drug_exposure_id from {{ ref('omop_drug_exposure') }}
    union all select 'measurement', measurement_id from {{ ref('omop_measurement') }}
    union all select 'observation', observation_id from {{ ref('omop_observation') }}
    union all select 'visit_occurrence', visit_occurrence_id from {{ ref('omop_visit_occurrence') }}
),

crosswalk as (
    select destination_table, omop_row_id from {{ ref('cw_event_crosswalk') }}
),

routed as (
    select destination_table, omop_event_id as omop_row_id
    from {{ ref('int_omop_events') }}
    where person_included
),

unexplained_candidates as (
    select c.source_event_key, c.mapping_ordinal
    from {{ ref('int_omop_event_candidates') }} as c
    where not exists (
              select 1 from {{ ref('int_omop_events') }} as e
              where e.source_event_key = c.source_event_key and e.mapping_ordinal = c.mapping_ordinal
                and e.person_included
          )
      and not exists (
              select 1 from {{ ref('int_exclusion_ledger') }} as l
              where l.source_key = c.source_event_key
                and l.exclusion_category in ('omop_routing', 'omop_person')
          )
)

(select 'cdm_row_without_crosswalk' as problem, destination_table, omop_row_id::text from cdm_rows
 except select 'cdm_row_without_crosswalk', destination_table, omop_row_id::text from crosswalk)
union all
(select 'crosswalk_without_cdm_row', destination_table, omop_row_id::text from crosswalk
 except select 'crosswalk_without_cdm_row', destination_table, omop_row_id::text from cdm_rows)
union all
(select 'routed_event_missing_from_cdm', destination_table, omop_row_id::text from routed
 except select 'routed_event_missing_from_cdm', destination_table, omop_row_id::text from cdm_rows)
union all
select 'candidate_neither_loaded_nor_ledgered', source_event_key, mapping_ordinal::text from unexplained_candidates
