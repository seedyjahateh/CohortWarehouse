{{ config(materialized='view') }}
-- Grain: one source clinical event (condition, medication or observation record) in a common shape,
-- used for vocabulary mapping, OMOP routing and coverage accounting. Filters on patient_id push down
-- through the UNION ALL into each event view.
select
    dataset_id, 'conditions' as source_file, source_event_key, patient_id, patient_exists, encounter_id,
    start_date, null::timestamptz as start_at, stop_date as end_date, null::timestamptz as end_at,
    source_system, source_vocabulary_id, vocabulary_assumed, source_code, source_description,
    null::text as source_category, null::text as value_text, null::numeric as value_as_number,
    null::text as value_parse_status, null::text as source_unit, null::text as canonical_unit,
    source_batch_id, source_record_number
from {{ ref('int_condition_events') }}

union all

select
    dataset_id, 'medications', source_event_key, patient_id, patient_exists, encounter_id,
    start_date, start_at, stop_date, stop_at,
    source_system, source_vocabulary_id, vocabulary_assumed, source_code, source_description,
    null, null, null, null, null, null,
    source_batch_id, source_record_number
from {{ ref('int_medication_events') }}

union all

select
    dataset_id, 'observations', source_event_key, patient_id, patient_exists, encounter_id,
    observation_date, observed_at, null::date, null::timestamptz,
    source_system, source_vocabulary_id, vocabulary_assumed, source_code, source_description,
    source_category, value_text, value_as_number, value_parse_status, source_unit, canonical_unit,
    source_batch_id, source_record_number
from {{ ref('int_observation_events') }}
