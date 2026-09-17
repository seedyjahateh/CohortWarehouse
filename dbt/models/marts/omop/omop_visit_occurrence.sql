{{
    config(
        alias='visit_occurrence',
        materialized='incremental',
        incremental_strategy='append',
        on_schema_change='fail',
        pre_hook=["{{ delete_changed_person_slice('person_id') }}"],
        post_hook=["{{ maybe_inject_failure() }}"],
        indexes=[{'columns': ['visit_occurrence_id'], 'unique': True}, {'columns': ['person_id']}]
    )
}}
-- depends_on: {{ ref('int_changed_person_keys') }}
-- Grain: one source encounter of an included person. visit_occurrence_id = star encounter_key.
-- Required visit_end_date uses the start date when STOP is absent (imputation recorded in
-- cw_event_crosswalk.end_date_imputed, never inside the CDM table).
select
    e.encounter_key::integer as visit_occurrence_id,
    e.patient_key::integer as person_id,
    coalesce(v.concept_id, 0)::integer as visit_concept_id,
    e.start_date as visit_start_date,
    {{ omop_datetime('e.start_at') }} as visit_start_datetime,
    coalesce(e.stop_date, e.start_date) as visit_end_date,
    {{ omop_datetime('e.stop_at') }} as visit_end_datetime,
    {{ fixed_concept('ehr_record_type') }}::integer as visit_type_concept_id,
    null::integer as provider_id,
    null::integer as care_site_id,
    e.encounter_class::varchar(50) as visit_source_value,
    0::integer as visit_source_concept_id,
    null::integer as admitted_from_concept_id,
    null::varchar(50) as admitted_from_source_value,
    null::integer as discharged_to_concept_id,
    null::varchar(50) as discharged_to_source_value,
    null::integer as preceding_visit_occurrence_id
from {{ ref('int_encounters') }} as e
inner join {{ ref('int_omop_persons') }} as op
    on op.patient_key = e.patient_key and op.is_included
left join {{ ref('int_omop_reference_concepts') }} as v
    on v.concept_role = 'visit' and v.source_value = e.encounter_class and v.invalid_reason is null
{% if is_incremental() %}
where e.patient_key in (select patient_key from {{ ref('int_changed_person_keys') }})
{% endif %}
