-- Grain protection: joining conditions to encounters (a common analyst join) must not change the distinct
-- encounter count, and each cohort's monthly encounter total must equal its members' distinct encounters in
-- the window (bi_cohort_month is pre-aggregated). Zero rows = pass.
with joined as (
    select count(distinct e.encounter_key) as distinct_via_join
    from {{ ref('fct_encounter') }} as e
    left join {{ ref('fct_condition') }} as c on c.encounter_key = e.encounter_key
),

direct as (
    select count(*) as encounter_rows, count(distinct encounter_key) as distinct_encounters
    from {{ ref('fct_encounter') }}
),

monthly as (
    select cohort_id, sum(encounter_count) as monthly_total
    from {{ ref('bi_cohort_month') }}
    group by cohort_id
),

members as (
    select m.cohort_id, count(distinct e.encounter_key) as window_encounters
    from {{ ref('bi_cohort_membership') }} as m
    inner join {{ ref('fct_encounter') }} as e on e.patient_key = m.patient_key
    where e.start_date between m.as_of_date - 364 and m.as_of_date
    group by m.cohort_id
)

select 'join_inflation' as problem, null::text as cohort_id, j.distinct_via_join::numeric as observed,
       d.distinct_encounters::numeric as expected
from joined as j cross join direct as d
where j.distinct_via_join <> d.distinct_encounters or d.encounter_rows <> d.distinct_encounters

union all

select 'monthly_total_mismatch', coalesce(mo.cohort_id, me.cohort_id), mo.monthly_total, me.window_encounters
from monthly as mo
full outer join members as me on me.cohort_id = mo.cohort_id
where coalesce(mo.monthly_total, 0) <> coalesce(me.window_encounters, 0)
