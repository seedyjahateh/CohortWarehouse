{{ config(indexes=[{'columns': ['cohort_id', 'patient_key'], 'unique': True}]) }}
-- Grain: one (cohort definition, eligible patient) membership with its qualifying evidence.
-- Clinical rules live here and are tested against independent SQL; DAX only aggregates.
with defs as (
    select d.*, rev.as_of_date
    from {{ ref('cohort_definitions') }} as d
    cross join {{ ref('stg_ops__selected_revision') }} as rev
),

snapshot as (
    select * from {{ ref('bi_patient_snapshot') }}
),

qualifying_conditions as (
    select
        d.cohort_id,
        c.patient_key,
        c.event_key,
        c.start_date,
        c.stop_date,
        c.source_code,
        row_number() over (
            partition by d.cohort_id, c.patient_key
            order by c.start_date desc, c.source_event_key desc
        ) as rn
    from defs as d
    inner join {{ ref('cohort_code_sets') }} as cs
        on cs.code_set_id = d.condition_code_set_id
    inner join {{ ref('int_conditions') }} as c
        on c.source_vocabulary_id = cs.omop_vocabulary_id and c.source_code = cs.source_code
    where c.start_date <= d.as_of_date
      and (c.stop_date is null or c.stop_date >= d.as_of_date)
),

window_encounters as (
    select
        e.patient_key,
        min(e.start_date) as first_encounter_date,
        max(e.start_date) as last_encounter_date
    from {{ ref('int_encounters') }} as e
    cross join (select as_of_date from {{ ref('stg_ops__selected_revision') }}) as rev
    where e.start_date between rev.as_of_date - 364 and rev.as_of_date
    group by e.patient_key
),

candidates as (
    select
        d.cohort_id,
        d.definition_version,
        d.as_of_date,
        s.patient_key,
        s.encounter_count_365d,
        s.latest_systolic_observation_key,
        s.latest_systolic_date,
        s.latest_systolic_value,
        s.systolic_tie_flag,
        s.has_valid_recent_systolic,
        qc.event_key as qualifying_condition_key,
        qc.start_date as qualifying_condition_start_date,
        qc.source_code as qualifying_condition_code,
        d.condition_code_set_id,
        d.measurement_code_set_id,
        d.systolic_threshold_exclusive,
        d.min_encounters
    from defs as d
    cross join snapshot as s
    left join qualifying_conditions as qc
        on qc.cohort_id = d.cohort_id and qc.patient_key = s.patient_key and qc.rn = 1
)

select
    c.cohort_id,
    c.definition_version,
    c.patient_key,
    c.as_of_date,
    case c.cohort_id
        when 'C1' then 'Recorded hypertension code active on the as-of date'
        when 'C2' then 'Recorded hypertension and latest valid systolic in window above threshold'
        when 'C3' then 'At least the minimum number of distinct encounters in the lookback window'
    end as membership_reason,
    c.qualifying_condition_key,
    c.qualifying_condition_start_date,
    c.qualifying_condition_code,
    case when c.measurement_code_set_id is not null then c.latest_systolic_observation_key end
        as qualifying_measurement_key,
    case when c.measurement_code_set_id is not null then c.latest_systolic_date end as qualifying_measurement_date,
    case when c.measurement_code_set_id is not null then c.latest_systolic_value end
        as qualifying_measurement_value,
    case when c.measurement_code_set_id is not null then c.systolic_tie_flag end as measurement_tie_flag,
    c.encounter_count_365d as window_encounter_count,
    w.first_encounter_date as window_first_encounter_date,
    w.last_encounter_date as window_last_encounter_date
from candidates as c
left join window_encounters as w on w.patient_key = c.patient_key
where c.encounter_count_365d >= c.min_encounters
  and (c.condition_code_set_id is null or c.qualifying_condition_key is not null)
  and (
      c.measurement_code_set_id is null
      or (c.has_valid_recent_systolic and c.latest_systolic_value > c.systolic_threshold_exclusive)
  )
