-- depends_on: {{ ref('int_key_registry') }}
-- Grain: one organization in the target batch's reference snapshot.
select
    k.surrogate_id as organization_key,
    o.*
from {{ ref('stg_synthea__organizations') }} as o
{{ key_lookup('organization', 'k', 'o.dataset_id', 'o.organization_id') }}
