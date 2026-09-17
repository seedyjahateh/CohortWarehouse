-- Grain: one (metric, dimension value). Achilles-style descriptive profile organised by DQD categories
-- (conformance / completeness / plausibility). This is NOT an Achilles or DQD run.
with rev as (
    select as_of_date, dataset_id, target_revision from {{ ref('stg_ops__selected_revision') }}
)

select 'completeness' as dqd_category, 'persons' as metric, 'all' as dimension_value,
       count(*)::numeric as value, 'people' as unit
from {{ ref('int_patients') }}

union all
select 'completeness', 'events', 'encounters', count(*), 'rows' from {{ ref('int_encounters') }}
union all
select 'completeness', 'events', 'conditions', count(*), 'rows' from {{ ref('int_conditions') }}
union all
select 'completeness', 'events', 'medications', count(*), 'rows' from {{ ref('int_medications') }}
union all
select 'completeness', 'events', 'observations', count(*), 'rows' from {{ ref('int_observations') }}

union all
select 'completeness', 'observation value status', value_parse_status, count(*), 'rows'
from {{ ref('int_observations') }} group by value_parse_status

union all
select 'conformance', 'unmapped source codes', source_files, count(*), 'codes'
from {{ ref('int_clinical_codes') }} where mapping_status not in ('standard_source', 'maps_to')
group by source_files

union all
select 'conformance', 'quarantined source rows', q.file_key || ': ' || q.reason, count(*), 'rows'
from {{ source('ops', 'quarantine') }} as q
inner join {{ source('ops', 'batch') }} as b on b.batch_id = q.batch_id
cross join rev
where b.dataset_id = rev.dataset_id and b.source_revision <= rev.target_revision
group by q.file_key, q.reason

union all
select 'conformance', 'exclusions', exclusion_category || ': ' || reason, count(*), 'records'
from {{ ref('int_exclusion_ledger') }} group by exclusion_category, reason

union all
select 'conformance', 'visit link status', encounter_link_status, count(*), 'condition rows'
from {{ ref('int_conditions') }} group by encounter_link_status

union all
select 'plausibility', 'measurement p50 by code and unit', source_code || ' [' || coalesce(source_unit, 'no unit') || ']',
       percentile_cont(0.5) within group (order by value_as_number)::numeric, coalesce(source_unit, '')
from {{ ref('int_observations') }} where value_parse_status = 'numeric'
group by source_code, source_unit

union all
select 'plausibility', 'encounter duration p50', encounter_class,
       percentile_cont(0.5) within group (order by duration_minutes)::numeric, 'minutes'
from {{ ref('int_encounters') }} where duration_minutes is not null group by encounter_class

union all
select 'conformance', 'stop before start (value nulled, event kept)', source_file, count(*), 'rows'
from {{ ref('int_exclusion_ledger') }}
where exclusion_category = 'data_quality' and reason = 'stop_before_start_nulled'
group by source_file

union all
select 'plausibility', 'encounters without stop time', 'all', count(*), 'rows'
from {{ ref('int_encounters') }} where stop_at is null

union all
select 'plausibility', 'events after as-of date', 'encounters', count(*), 'rows'
from {{ ref('int_encounters') }} cross join rev where start_date > rev.as_of_date

union all
select 'plausibility', 'observation period length p50', 'included persons',
       percentile_cont(0.5) within group (order by observation_period_end_date - observation_period_start_date)::numeric,
       'days'
from {{ ref('int_omop_persons') }} where is_included

union all
select 'plausibility', 'mapping fan-out', 'events with >1 OMOP row', count(*), 'events'
from (
    select source_event_key from {{ ref('int_omop_event_candidates') }}
    group by source_event_key having count(*) > 1
) as fanout

union all
select 'completeness', 'eligible patients by age band', age_band, count(*), 'people'
from {{ ref('bi_patient_snapshot') }} group by age_band
