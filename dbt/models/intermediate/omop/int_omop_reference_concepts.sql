{{ config(materialized='table') }}
-- Grain: one (concept role, source value). Resolves every seed-declared concept by vocabulary + code
-- against the loaded vocabulary; ids are never hard-coded. Unresolvable rows keep concept_id null and
-- fail tests/assert_reference_concepts_resolve.sql (except deliberate blank-code "concept 0" rows).
with declared as (
    select 'fixed:' || role as concept_role, role as source_value, omop_vocabulary_id, omop_concept_code,
           expected_domain_id
    from {{ ref('omop_fixed_concepts') }}
    union all
    select 'demographic:' || dimension, source_value, omop_vocabulary_id, omop_concept_code,
           case dimension when 'gender' then 'Gender' when 'race' then 'Race' else 'Ethnicity' end
    from {{ ref('demographic_concepts') }}
    union all
    select 'visit', source_class, omop_visit_vocabulary_id, omop_visit_concept_code, 'Visit'
    from {{ ref('encounter_classes') }}
)

select
    d.concept_role,
    d.source_value,
    d.omop_vocabulary_id,
    d.omop_concept_code,
    d.expected_domain_id,
    d.omop_concept_code is null as is_declared_unmapped,
    c.concept_id,
    c.concept_name,
    c.domain_id,
    c.standard_concept,
    c.invalid_reason
from declared as d
left join {{ source('vocab', 'concept') }} as c
    on c.vocabulary_id = d.omop_vocabulary_id
   and c.concept_code = d.omop_concept_code
