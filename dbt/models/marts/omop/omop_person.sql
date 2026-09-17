{{ config(alias='person', indexes=[{'columns': ['person_id'], 'unique': True}]) }}
-- Grain: one included person (CDM 5.4 PERSON). person_id = the star patient_key (Section 8.4.2).
-- person_source_value is a pseudonymous hash, never the source UUID.
select
    p.patient_key::integer as person_id,
    coalesce(g.concept_id, 0)::integer as gender_concept_id,
    extract(year from p.birth_date)::integer as year_of_birth,
    extract(month from p.birth_date)::integer as month_of_birth,
    extract(day from p.birth_date)::integer as day_of_birth,
    null::timestamp as birth_datetime,
    coalesce(r.concept_id, 0)::integer as race_concept_id,
    coalesce(e.concept_id, 0)::integer as ethnicity_concept_id,
    null::integer as location_id,
    null::integer as provider_id,
    null::integer as care_site_id,
    p.patient_pseudo_id::varchar(50) as person_source_value,
    p.gender::varchar(50) as gender_source_value,
    0::integer as gender_source_concept_id,
    p.race::varchar(50) as race_source_value,
    0::integer as race_source_concept_id,
    p.ethnicity::varchar(50) as ethnicity_source_value,
    0::integer as ethnicity_source_concept_id
from {{ ref('int_patients') }} as p
inner join {{ ref('int_omop_persons') }} as op
    on op.patient_key = p.patient_key and op.is_included
left join {{ ref('int_omop_reference_concepts') }} as g
    on g.concept_role = 'demographic:gender' and g.source_value = p.gender and g.invalid_reason is null
left join {{ ref('int_omop_reference_concepts') }} as r
    on r.concept_role = 'demographic:race' and r.source_value = p.race and r.invalid_reason is null
left join {{ ref('int_omop_reference_concepts') }} as e
    on e.concept_role = 'demographic:ethnicity' and e.source_value = p.ethnicity and e.invalid_reason is null
