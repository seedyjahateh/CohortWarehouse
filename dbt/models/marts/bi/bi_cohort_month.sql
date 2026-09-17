-- Grain: one (cohort definition, member, encounter-start month) within the definition's encounter window,
-- with the pre-aggregated DISTINCT encounter count. Month filters affect utilisation only, never the
-- fixed membership or as-of date.
with rev as (
    select as_of_date from {{ ref('stg_ops__selected_revision') }}
)

select
    m.cohort_id,
    m.definition_version,
    m.patient_key,
    date_trunc('month', e.start_date::timestamp)::date as encounter_month,
    to_char(e.start_date, 'YYYYMM')::integer as month_key,
    count(distinct e.encounter_key) as encounter_count
from {{ ref('bi_cohort_membership') }} as m
inner join {{ ref('int_encounters') }} as e
    on e.patient_key = m.patient_key
cross join rev
where e.start_date between rev.as_of_date - 364 and rev.as_of_date
group by m.cohort_id, m.definition_version, m.patient_key, date_trunc('month', e.start_date::timestamp), to_char(e.start_date, 'YYYYMM')
