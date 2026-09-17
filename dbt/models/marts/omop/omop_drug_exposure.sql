{{
    config(
        alias='drug_exposure',
        materialized='incremental',
        incremental_strategy='append',
        on_schema_change='fail',
        pre_hook=["{{ delete_changed_person_slice('person_id') }}"],
        post_hook=["{{ maybe_inject_failure() }}"],
        indexes=[{'columns': ['drug_exposure_id'], 'unique': True}, {'columns': ['person_id']}]
    )
}}
-- depends_on: {{ ref('int_changed_person_keys') }}
-- Grain: one source medication record per target concept. Missing required end date uses the start date
-- (documented conservative convention, flagged in cw_event_crosswalk). No inference of adherence,
-- administration, days supply, route, dose, quantity or individual fills.
select
    omop_event_id::integer as drug_exposure_id,
    person_id::integer as person_id,
    target_concept_id::integer as drug_concept_id,
    start_date as drug_exposure_start_date,
    {{ omop_datetime('start_at') }} as drug_exposure_start_datetime,
    coalesce(end_date, start_date) as drug_exposure_end_date,
    {{ omop_datetime('end_at') }} as drug_exposure_end_datetime,
    end_date as verbatim_end_date,
    {{ fixed_concept('ehr_record_type') }}::integer as drug_type_concept_id,
    null::varchar(20) as stop_reason,
    null::integer as refills,
    null::numeric as quantity,
    null::integer as days_supply,
    null::text as sig,
    null::integer as route_concept_id,
    null::varchar(50) as lot_number,
    null::integer as provider_id,
    visit_occurrence_id::integer as visit_occurrence_id,
    null::integer as visit_detail_id,
    left(source_code, 50)::varchar(50) as drug_source_value,
    source_concept_id::integer as drug_source_concept_id,
    null::varchar(50) as route_source_value,
    null::varchar(50) as dose_unit_source_value
from {{ ref('int_omop_events') }}
{{ omop_event_where('drug_exposure') }}
