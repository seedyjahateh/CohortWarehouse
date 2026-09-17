{{
    config(
        alias='condition_occurrence',
        materialized='incremental',
        incremental_strategy='append',
        on_schema_change='fail',
        pre_hook=["{{ delete_changed_person_slice('person_id') }}"],
        post_hook=["{{ maybe_inject_failure() }}"],
        indexes=[{'columns': ['condition_occurrence_id'], 'unique': True}, {'columns': ['person_id']}]
    )
}}
-- depends_on: {{ ref('int_changed_person_keys') }}
-- Grain: one routed Condition-domain row per (source event, target concept). No invented status/severity.
select
    omop_event_id::integer as condition_occurrence_id,
    person_id::integer as person_id,
    target_concept_id::integer as condition_concept_id,
    start_date as condition_start_date,
    {{ omop_datetime('start_at') }} as condition_start_datetime,
    end_date as condition_end_date,
    {{ omop_datetime('end_at') }} as condition_end_datetime,
    {{ fixed_concept('ehr_record_type') }}::integer as condition_type_concept_id,
    null::integer as condition_status_concept_id,
    null::varchar(20) as stop_reason,
    null::integer as provider_id,
    visit_occurrence_id::integer as visit_occurrence_id,
    null::integer as visit_detail_id,
    left(source_code, 50)::varchar(50) as condition_source_value,
    source_concept_id::integer as condition_source_concept_id,
    null::varchar(50) as condition_status_source_value
from {{ ref('int_omop_events') }}
{{ omop_event_where('condition_occurrence') }}
