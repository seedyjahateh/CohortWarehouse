-- Conservation (STG-05, Section 11.3): every source record of the selected revision is accounted for exactly
-- once - either as a keyed intermediate event (valid patient) or as an orphan exclusion - and every keyed
-- event reaches its star fact exactly once. Returns one row per imbalance (zero rows = pass).
with source_counts as (
    select 'encounters' as source_file, count(*) as n from {{ ref('stg_synthea__encounters') }}
    union all select 'conditions', count(*) from {{ ref('stg_synthea__conditions') }}
    union all select 'medications', count(*) from {{ ref('stg_synthea__medications') }}
    union all select 'observations', count(*) from {{ ref('stg_synthea__observations') }}
),

keyed_counts as (
    select 'encounters' as source_file, count(*) as n from {{ ref('int_encounters') }}
    union all select 'conditions', count(*) from {{ ref('int_conditions') }}
    union all select 'medications', count(*) from {{ ref('int_medications') }}
    union all select 'observations', count(*) from {{ ref('int_observations') }}
),

orphan_counts as (
    select source_file, count(*) as n
    from {{ ref('int_exclusion_ledger') }}
    where exclusion_category = 'orphan_patient'
    group by source_file
),

fact_counts as (
    select 'encounters' as source_file, count(*) as n from {{ ref('fct_encounter') }}
    union all select 'conditions', count(*) from {{ ref('fct_condition') }}
    union all select 'medications', count(*) from {{ ref('fct_medication') }}
    union all select 'observations', count(*) from {{ ref('fct_observation') }}
)

select
    s.source_file,
    s.n as source_records,
    k.n as keyed_events,
    coalesce(o.n, 0) as orphan_exclusions,
    f.n as star_fact_rows
from source_counts as s
inner join keyed_counts as k on k.source_file = s.source_file
inner join fact_counts as f on f.source_file = s.source_file
left join orphan_counts as o on o.source_file = s.source_file
where s.n <> k.n + coalesce(o.n, 0)
   or k.n <> f.n
