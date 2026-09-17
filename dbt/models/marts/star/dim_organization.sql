-- Grain: one organization in the current reference snapshot, plus key 0 = Unknown / not supplied. Type 1.
select organization_key, organization_name, city, state, false as is_unknown_member
from {{ ref('int_organizations') }}

union all

select 0, 'Unknown organization', null, null, true
