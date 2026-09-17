{{
    config(
        alias='observation',
        materialized='incremental',
        incremental_strategy='append',
        on_schema_change='fail',
        pre_hook=["{{ delete_changed_person_slice('person_id') }}"],
        post_hook=["{{ maybe_inject_failure() }}"],
        indexes=[{'columns': ['observation_id'], 'unique': True}, {'columns': ['person_id']}]
    )
}}
-- depends_on: {{ ref('int_changed_person_keys') }}
-- Grain: one Observation-domain row per (source event, target concept), from any input file
-- (routing is by target domain). 'Maps to value' targets populate value_as_concept_id.
select
    e.omop_event_id::integer as observation_id,
    e.person_id::integer as person_id,
    e.target_concept_id::integer as observation_concept_id,
    e.start_date as observation_date,
    {{ omop_datetime('e.start_at') }} as observation_datetime,
    {{ fixed_concept('ehr_record_type') }}::integer as observation_type_concept_id,
    case when e.value_parse_status = 'numeric' then e.value_as_number end as value_as_number,
    case when e.value_parse_status = 'text' then left(e.value_text, 60) end::varchar(60) as value_as_string,
    e.value_as_concept_id::integer as value_as_concept_id,
    null::integer as qualifier_concept_id,
    case when e.source_unit is null then null else coalesce(u.unit_concept_id, 0) end::integer as unit_concept_id,
    null::integer as provider_id,
    e.visit_occurrence_id::integer as visit_occurrence_id,
    null::integer as visit_detail_id,
    left(e.source_code, 50)::varchar(50) as observation_source_value,
    e.source_concept_id::integer as observation_source_concept_id,
    left(e.source_unit, 50)::varchar(50) as unit_source_value,
    null::varchar(50) as qualifier_source_value,
    left(e.value_text, 50)::varchar(50) as value_source_value,
    null::integer as observation_event_id,
    null::integer as obs_event_field_concept_id
from {{ ref('int_omop_events') }} as e
left join {{ ref('int_units') }} as u
    on u.dataset_id = e.dataset_id and u.source_unit = e.source_unit
{{ omop_event_where('observation') }}
