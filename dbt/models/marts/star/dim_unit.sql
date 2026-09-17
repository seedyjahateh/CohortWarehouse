-- Grain: one supplied unit string, plus key 0 = no unit supplied. Type 1; versioned unit policy.
select
    unit_key,
    source_unit,
    canonical_unit,
    approved_for_systolic,
    policy_version,
    unit_concept_id,
    unit_mapping_status,
    false as is_unknown_member
from {{ ref('int_units') }}

union all

select 0, null, null, false, null, null, 'no_unit_supplied', true
