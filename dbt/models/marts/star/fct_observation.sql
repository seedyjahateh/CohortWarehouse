{{
    config(
        materialized='incremental',
        incremental_strategy='append',
        on_schema_change='fail',
        pre_hook=["{{ delete_changed_person_slice() }}"],
        post_hook=["{{ maybe_inject_failure() }}"],
        indexes=[{'columns': ['observation_key'], 'unique': True}, {'columns': ['patient_key']}]
    )
}}
-- depends_on: {{ ref('int_changed_person_keys') }}
-- Grain: one source observation row, including repeated same-time values.
-- Never sum value_as_number across codes or units.
select
    event_key as observation_key,
    patient_key,
    {{ date_key('observation_date') }} as observation_date_key,
    clinical_code_key,
    unit_key,
    encounter_key,
    encounter_link_status,
    observed_at,
    observation_date,
    value_as_number,
    value_text as source_value_text,
    value_parse_status,
    source_value_type,
    source_category,
    source_unit,
    canonical_unit,
    1 as observation_count,
    source_event_key,
    source_batch_id,
    source_record_number
from {{ ref('int_observations') }}
{{ changed_person_filter() }}
