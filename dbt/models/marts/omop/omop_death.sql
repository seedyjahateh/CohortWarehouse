{{ config(alias='death') }}
-- Grain: at most one row per included person with a supplied death date on/before D. No invented cause.
select
    p.patient_key::integer as person_id,
    p.death_date,
    null::timestamp as death_datetime,
    {{ fixed_concept('ehr_record_type') }}::integer as death_type_concept_id,
    null::integer as cause_concept_id,
    null::varchar(50) as cause_source_value,
    null::integer as cause_source_concept_id
from {{ ref('int_patients') }} as p
inner join {{ ref('int_omop_persons') }} as op
    on op.patient_key = p.patient_key and op.is_included
where p.death_date is not null
  and p.death_date <= op.as_of_date
