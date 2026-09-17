-- Grain: one calendar month in the 365-day encounter window ending at D. Filters bi_cohort_month only.
with rev as (
    select as_of_date from {{ ref('stg_ops__selected_revision') }}
)

select
    to_char(m, 'YYYYMM')::integer as month_key,
    m::date as month_start_date,
    to_char(m, 'Mon YYYY') as month_label,
    extract(year from m)::integer as calendar_year,
    extract(month from m)::integer as calendar_month
from rev
cross join generate_series(
    date_trunc('month', (rev.as_of_date - 364)::timestamp),
    date_trunc('month', rev.as_of_date::timestamp),
    interval '1 month'
) as m
