{{
    config(
        materialized='incremental',
        incremental_strategy='append',
        on_schema_change='fail',
        pre_hook=["{{ delete_changed_person_slice() }}"],
        post_hook=["{{ maybe_inject_failure() }}"],
        indexes=[{'columns': ['condition_key'], 'unique': True}, {'columns': ['patient_key']}]
    )
}}
-- depends_on: {{ ref('int_changed_person_keys') }}
-- Grain: one preserved source condition occurrence (identical rows keep their multiplicity).
select
    event_key as condition_key,
    patient_key,
    {{ date_key('start_date') }} as start_date_key,
    {{ date_key('stop_date') }} as end_date_key,
    clinical_code_key,
    encounter_key,
    encounter_link_status,
    start_date,
    stop_date as end_date,
    1 as condition_count,
    source_event_key,
    source_batch_id,
    source_record_number
from {{ ref('int_conditions') }}
{{ changed_person_filter() }}
