-- Terminology (Section 11.1): every non-zero concept populated in the OMOP mart exists in the loaded
-- vocabulary, is valid, and - for clinical target and type columns - is standard and in the expected domain.
-- A clinical concept can never stand in for a type/provenance concept. Zero rows = pass.
with used as (
    select 'person.gender' as usage, gender_concept_id as concept_id, 'Gender' as expected_domain, true as must_be_standard from {{ ref('omop_person') }}
    union all select 'person.race', race_concept_id, 'Race', true from {{ ref('omop_person') }}
    union all select 'person.ethnicity', ethnicity_concept_id, 'Ethnicity', true from {{ ref('omop_person') }}
    union all select 'visit.visit_concept', visit_concept_id, 'Visit', true from {{ ref('omop_visit_occurrence') }}
    union all select 'visit.type', visit_type_concept_id, 'Type Concept', true from {{ ref('omop_visit_occurrence') }}
    union all select 'condition.concept', condition_concept_id, 'Condition', true from {{ ref('omop_condition_occurrence') }}
    union all select 'condition.type', condition_type_concept_id, 'Type Concept', true from {{ ref('omop_condition_occurrence') }}
    union all select 'condition.source', condition_source_concept_id, null, false from {{ ref('omop_condition_occurrence') }}
    union all select 'drug.concept', drug_concept_id, 'Drug', true from {{ ref('omop_drug_exposure') }}
    union all select 'drug.type', drug_type_concept_id, 'Type Concept', true from {{ ref('omop_drug_exposure') }}
    union all select 'drug.source', drug_source_concept_id, null, false from {{ ref('omop_drug_exposure') }}
    union all select 'measurement.concept', measurement_concept_id, 'Measurement', true from {{ ref('omop_measurement') }}
    union all select 'measurement.type', measurement_type_concept_id, 'Type Concept', true from {{ ref('omop_measurement') }}
    union all select 'measurement.unit', unit_concept_id, 'Unit', true from {{ ref('omop_measurement') }}
    union all select 'measurement.value', value_as_concept_id, null, false from {{ ref('omop_measurement') }}
    union all select 'measurement.source', measurement_source_concept_id, null, false from {{ ref('omop_measurement') }}
    union all select 'observation.concept', observation_concept_id, 'Observation', true from {{ ref('omop_observation') }}
    union all select 'observation.type', observation_type_concept_id, 'Type Concept', true from {{ ref('omop_observation') }}
    union all select 'observation.unit', unit_concept_id, 'Unit', true from {{ ref('omop_observation') }}
    union all select 'observation.value', value_as_concept_id, null, false from {{ ref('omop_observation') }}
    union all select 'observation.source', observation_source_concept_id, null, false from {{ ref('omop_observation') }}
    union all select 'period.type', period_type_concept_id, 'Type Concept', true from {{ ref('omop_observation_period') }}
    union all select 'death.type', death_type_concept_id, 'Type Concept', true from {{ ref('omop_death') }}
)

select u.usage, u.concept_id, u.expected_domain, c.domain_id, c.standard_concept, c.invalid_reason,
       count(*) as rows_affected
from used as u
left join {{ source('vocab', 'concept') }} as c on c.concept_id = u.concept_id
where u.concept_id is not null
  and u.concept_id <> 0
  and (
      c.concept_id is null
      or c.invalid_reason is not null
      or (u.must_be_standard and coalesce(c.standard_concept, '') <> 'S')
      or (u.expected_domain is not null and c.domain_id <> u.expected_domain)
  )
group by 1, 2, 3, 4, 5, 6
