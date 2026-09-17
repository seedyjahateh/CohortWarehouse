-- depends_on: {{ ref('int_key_registry') }}
-- Grain: one supplied unit string used by a valid observation in the selected revision.
with units as (
    select dataset_id, source_unit, count(*) as event_count
    from {{ ref('int_observations') }}
    where source_unit is not null
    group by dataset_id, source_unit
)

select
    k.surrogate_id as unit_key,
    u.dataset_id,
    u.source_unit,
    policy.canonical_unit,
    coalesce(policy.approved_for_systolic, false) as approved_for_systolic,
    policy.policy_version,
    coalesce(c.concept_id, 0) as unit_concept_id,
    case
        when policy.source_unit is null then 'not_in_policy'
        when c.concept_id is null then 'no_unit_concept'
        else 'mapped'
    end as unit_mapping_status,
    u.event_count
from units as u
left join {{ ref('unit_policy') }} as policy
    on policy.source_unit = u.source_unit
left join {{ source('vocab', 'concept') }} as c
    on c.vocabulary_id = 'UCUM'
   and c.concept_code = policy.ucum_code
   and c.standard_concept = 'S'
   and c.invalid_reason is null
{{ key_lookup('unit', 'k', 'u.dataset_id', 'u.source_unit') }}
