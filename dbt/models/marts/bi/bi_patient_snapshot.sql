{{ config(indexes=[{'columns': ['patient_key'], 'unique': True}]) }}
-- Grain: one ELIGIBLE patient at as-of date D (Section 5.4 common semantics):
--   completed-years age >= 18 on D; alive at the end of D (death on D = not alive);
--   >= 1 encounter starting in [D - 364, D] (UTC dates).
-- This is the common denominator for every cohort. No names, addresses, birth dates or source ids.
with rev as (
    select as_of_date from {{ ref('stg_ops__selected_revision') }}
),

window_encounters as (
    select e.patient_key, count(distinct e.encounter_key) as encounter_count_365d
    from {{ ref('int_encounters') }} as e
    cross join rev
    where e.start_date between rev.as_of_date - 364 and rev.as_of_date
    group by e.patient_key
),

eligible as (
    select
        p.patient_key,
        p.patient_pseudo_id,
        rev.as_of_date,
        extract(year from age(rev.as_of_date, p.birth_date))::integer as age_at_as_of,
        p.gender as recorded_sex,
        p.race,
        p.ethnicity,
        p.state,
        w.encounter_count_365d
    from {{ ref('int_patients') }} as p
    cross join rev
    inner join window_encounters as w on w.patient_key = p.patient_key
    where extract(year from age(rev.as_of_date, p.birth_date)) >= 18
      and (p.death_date is null or p.death_date > rev.as_of_date)
),

systolic_code as (
    select omop_vocabulary_id, source_code
    from {{ ref('cohort_code_sets') }}
    where code_set_id = 'SYSTOLIC_BP'
),

recent_systolic as (
    select o.*
    from {{ ref('int_observations') }} as o
    inner join systolic_code as s
        on s.omop_vocabulary_id = o.source_vocabulary_id and s.source_code = o.source_code
    cross join rev
    where o.observation_date between rev.as_of_date - 89 and rev.as_of_date
),

valid_ranked as (
    -- Latest VALID value: numeric and an approved unit. Ties on the instant are broken by the greatest
    -- stable source event key and flagged. Never max(value).
    select
        patient_key,
        event_key,
        source_event_key,
        observed_at,
        observation_date,
        value_as_number,
        row_number() over (partition by patient_key order by observed_at desc, source_event_key desc) as rn,
        count(*) over (partition by patient_key, observed_at) as same_instant_count
    from recent_systolic
    where value_parse_status = 'numeric' and unit_approved_for_systolic
),

systolic_quality as (
    select
        patient_key,
        count(*) filter (where value_parse_status = 'missing') as missing_value_count,
        count(*) filter (where value_parse_status = 'invalid') as invalid_value_count,
        count(*) filter (where value_parse_status = 'numeric' and not unit_approved_for_systolic)
            as unapproved_unit_count
    from recent_systolic
    group by patient_key
)

select
    e.patient_key,
    e.patient_pseudo_id,
    e.as_of_date,
    e.age_at_as_of,
    case
        when e.age_at_as_of < 30 then '18-29'
        when e.age_at_as_of < 45 then '30-44'
        when e.age_at_as_of < 65 then '45-64'
        when e.age_at_as_of < 75 then '65-74'
        else '75+'
    end as age_band,
    case
        when e.age_at_as_of < 30 then 1
        when e.age_at_as_of < 45 then 2
        when e.age_at_as_of < 65 then 3
        when e.age_at_as_of < 75 then 4
        else 5
    end as age_band_sort,
    coalesce(e.recorded_sex, 'Not recorded') as recorded_sex,
    coalesce(e.race, 'not recorded') as race,
    coalesce(e.ethnicity, 'not recorded') as ethnicity,
    coalesce(e.state, 'Not recorded') as state,
    e.encounter_count_365d,
    v.value_as_number as latest_systolic_value,
    v.observed_at as latest_systolic_at,
    v.observation_date as latest_systolic_date,
    v.event_key as latest_systolic_observation_key,
    v.event_key is not null as has_valid_recent_systolic,
    coalesce(v.same_instant_count > 1, false) as systolic_tie_flag,
    coalesce(q.missing_value_count, 0) as recent_systolic_missing_value_count,
    coalesce(q.invalid_value_count, 0) as recent_systolic_invalid_value_count,
    coalesce(q.unapproved_unit_count, 0) as recent_systolic_unapproved_unit_count
from eligible as e
left join valid_ranked as v on v.patient_key = e.patient_key and v.rn = 1
left join systolic_quality as q on q.patient_key = e.patient_key
