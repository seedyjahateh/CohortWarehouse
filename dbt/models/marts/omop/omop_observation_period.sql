{{ config(alias='observation_period') }}
-- Grain: one inferred observation period per included person. observation_period_id = person_id
-- (exactly one span per person). Inferred from supported events; not evidence of continuous coverage.
select
    patient_key::integer as observation_period_id,
    patient_key::integer as person_id,
    observation_period_start_date,
    observation_period_end_date,
    {{ fixed_concept('ehr_record_type') }}::integer as period_type_concept_id
from {{ ref('int_omop_persons') }}
where is_included
