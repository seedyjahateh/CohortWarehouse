{{
    config(
        materialized='incremental',
        incremental_strategy='append',
        on_schema_change='fail',
        pre_hook=["{{ delete_changed_person_slice() }}"],
        post_hook=["{{ maybe_inject_failure() }}"],
        indexes=[{'columns': ['encounter_key'], 'unique': True}, {'columns': ['patient_key']}]
    )
}}
-- depends_on: {{ ref('int_changed_person_keys') }}
-- Grain: one source encounter. Incremental by changed-person slice (Section 9.2).
-- Source costs are synthetic attributes, kept separate and never summed into a "total cost".
select
    encounter_key,
    patient_key,
    {{ date_key('start_date') }} as start_date_key,
    {{ date_key('stop_date') }} as end_date_key,
    organization_key,
    organization_link_status,
    encounter_type_key,
    start_at,
    stop_at,
    start_date,
    stop_date,
    duration_minutes,
    encounter_id as source_encounter_id,
    encounter_code as source_encounter_code,
    1 as encounter_count,
    base_encounter_cost as source_base_encounter_cost,
    total_claim_cost as source_total_claim_cost,
    source_row_fingerprint as source_event_key,
    source_batch_id,
    source_record_number
from {{ ref('int_encounters') }}
{{ changed_person_filter() }}
