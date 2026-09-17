{{
    config(
        alias='measurement',
        materialized='incremental',
        incremental_strategy='append',
        on_schema_change='fail',
        pre_hook=["{{ delete_changed_person_slice('person_id') }}"],
        post_hook=["{{ maybe_inject_failure() }}"],
        indexes=[{'columns': ['measurement_id'], 'unique': True}, {'columns': ['person_id']}]
    )
}}
-- depends_on: {{ ref('int_changed_person_keys') }}
-- Grain: one Measurement-domain row per (source event, target concept). Text is never coerced to a number
-- and a missing value is never zero. unit_concept_id: null = no unit supplied, 0 = supplied but unmapped.
select
    e.omop_event_id::integer as measurement_id,
    e.person_id::integer as person_id,
    e.target_concept_id::integer as measurement_concept_id,
    e.start_date as measurement_date,
    {{ omop_datetime('e.start_at') }} as measurement_datetime,
    null::varchar(10) as measurement_time,
    {{ fixed_concept('ehr_record_type') }}::integer as measurement_type_concept_id,
    null::integer as operator_concept_id,
    case when e.value_parse_status = 'numeric' then e.value_as_number end as value_as_number,
    e.value_as_concept_id::integer as value_as_concept_id,
    case when e.source_unit is null then null else coalesce(u.unit_concept_id, 0) end::integer as unit_concept_id,
    null::numeric as range_low,
    null::numeric as range_high,
    null::integer as provider_id,
    e.visit_occurrence_id::integer as visit_occurrence_id,
    null::integer as visit_detail_id,
    left(e.source_code, 50)::varchar(50) as measurement_source_value,
    e.source_concept_id::integer as measurement_source_concept_id,
    left(e.source_unit, 50)::varchar(50) as unit_source_value,
    null::integer as unit_source_concept_id,
    left(e.value_text, 50)::varchar(50) as value_source_value,
    null::integer as measurement_event_id,
    null::integer as meas_event_field_concept_id
from {{ ref('int_omop_events') }} as e
left join {{ ref('int_units') }} as u
    on u.dataset_id = e.dataset_id and u.source_unit = e.source_unit
{{ omop_event_where('measurement') }}
