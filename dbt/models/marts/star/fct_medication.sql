{{
    config(
        materialized='incremental',
        incremental_strategy='append',
        on_schema_change='fail',
        pre_hook=["{{ delete_changed_person_slice() }}"],
        post_hook=["{{ maybe_inject_failure() }}"],
        indexes=[{'columns': ['medication_key'], 'unique': True}, {'columns': ['patient_key']}]
    )
}}
-- depends_on: {{ ref('int_changed_person_keys') }}
-- Grain: one source medication row. Dispenses/costs are recorded source values; no adherence or fill
-- inference is made.
select
    event_key as medication_key,
    patient_key,
    {{ date_key('start_date') }} as start_date_key,
    {{ date_key('stop_date') }} as end_date_key,
    clinical_code_key,
    encounter_key,
    encounter_link_status,
    start_at,
    stop_at,
    start_date,
    stop_date as end_date,
    dispenses as source_dispenses,
    dispenses_status as source_dispenses_status,
    base_cost as source_base_cost,
    total_cost as source_total_cost,
    1 as medication_count,
    source_event_key,
    source_batch_id,
    source_record_number
from {{ ref('int_medications') }}
{{ changed_person_filter() }}
