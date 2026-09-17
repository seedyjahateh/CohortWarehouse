-- depends_on: {{ ref('int_key_registry') }}
-- Grain: one normalised encounter class from the versioned seed, plus key 0 = Unknown. Type 1.
select
    k.surrogate_id as encounter_type_key,
    s.source_class,
    s.reporting_label,
    s.reporting_group,
    s.review_status,
    false as is_unknown_member
from {{ ref('encounter_classes') }} as s
cross join {{ ref('stg_ops__selected_revision') }} as rev
{{ key_lookup('encounter_type', 'k', 'rev.dataset_id', 's.source_class') }}

union all

select 0, null, 'Unknown', 'Unknown', null, true
