{{ config(indexes=[{'columns': ['date_key'], 'unique': True}]) }}
-- Grain: one calendar date (Type 0) spanning every referenced event start/end date and D.
-- date_key 0 = no date supplied (e.g. an open-ended condition).
with referenced as (
    select start_date as d from {{ ref('int_encounters') }}
    union all select stop_date from {{ ref('int_encounters') }}
    union all select start_date from {{ ref('int_conditions') }}
    union all select stop_date from {{ ref('int_conditions') }}
    union all select start_date from {{ ref('int_medications') }}
    union all select stop_date from {{ ref('int_medications') }}
    union all select observation_date from {{ ref('int_observations') }}
    union all select as_of_date from {{ ref('stg_ops__selected_revision') }}
),

bounds as (
    select min(d) as first_date, max(d) as last_date from referenced where d is not null
),

calendar as (
    select generate_series(first_date, last_date, interval '1 day')::date as full_date from bounds
)

select
    to_char(full_date, 'YYYYMMDD')::integer as date_key,
    full_date,
    extract(year from full_date)::integer as calendar_year,
    extract(quarter from full_date)::integer as calendar_quarter,
    extract(month from full_date)::integer as calendar_month,
    to_char(full_date, 'FMMonth') as month_name,
    date_trunc('month', full_date::timestamp)::date as month_start_date,
    extract(isoyear from full_date)::integer as iso_year,
    extract(week from full_date)::integer as iso_week,
    extract(day from full_date)::integer as day_of_month,
    extract(isodow from full_date)::integer as iso_day_of_week,
    to_char(full_date, 'FMDay') as day_name,
    extract(isodow from full_date) in (6, 7) as is_weekend
from calendar

union all

select 0, null, null, null, null, 'Unknown', null, null, null, null, null, 'Unknown', null
