-- Terminology gate: (a) every seed-declared fixed/demographic/visit concept with a code resolves to exactly
-- one valid concept in the expected domain; (b) every cohort code resolves in the pinned vocabulary to at
-- least one valid standard target (MAP-06: 100% for cohort codes), whether or not it occurs in the data.
with reference_problems as (
    select 'reference_concept' as problem, concept_role || ':' || source_value as item,
           count(concept_id) as resolved_concepts
    from {{ ref('int_omop_reference_concepts') }}
    where not is_declared_unmapped
    group by concept_role, source_value
    having count(concept_id) <> 1
        or bool_or(invalid_reason is not null)
        or bool_or(domain_id is distinct from expected_domain_id)
),

cohort_codes as (
    select cs.code_set_id, cs.omop_vocabulary_id, cs.source_code, src.concept_id as source_concept_id,
           src.standard_concept, src.invalid_reason
    from {{ ref('cohort_code_sets') }} as cs
    left join {{ source('vocab', 'concept') }} as src
        on src.vocabulary_id = cs.omop_vocabulary_id and src.concept_code = cs.source_code
),

cohort_targets as (
    select cc.code_set_id, cc.source_code, count(t.concept_id) as valid_targets
    from cohort_codes as cc
    left join {{ source('vocab', 'concept_relationship') }} as cr
        on cr.concept_id_1 = cc.source_concept_id and cr.relationship_id = 'Maps to' and cr.invalid_reason is null
    left join {{ source('vocab', 'concept') }} as t
        on t.concept_id = case when cc.standard_concept = 'S' and cc.invalid_reason is null
                               then cc.source_concept_id else cr.concept_id_2 end
       and t.standard_concept = 'S' and t.invalid_reason is null
    group by cc.code_set_id, cc.source_code
)

select problem, item, resolved_concepts from reference_problems
union all
select 'cohort_code_unmapped', code_set_id || ':' || source_code, valid_targets
from cohort_targets
where valid_targets = 0
