{{ config(indexes=[{'columns': ['patient_key'], 'unique': True}]) }}
-- Grain: one patient in the selected revision. Type 1: corrections overwrite attributes, key is stable.
-- Birth date is kept only in this protected analytical layer; BI receives age at D instead.
with event_dates as (
    select patient_key, start_date as event_date from {{ ref('int_encounters') }}
    union all
    select patient_key, start_date from {{ ref('int_conditions') }}
    union all
    select patient_key, start_date from {{ ref('int_medications') }}
    union all
    select patient_key, observation_date from {{ ref('int_observations') }}
),

bounds as (
    select patient_key, min(event_date) as first_event_date, max(event_date) as last_event_date,
           count(*) as recorded_event_rows
    from event_dates
    group by patient_key
)

select
    p.patient_key,
    p.dataset_id,
    p.patient_pseudo_id,
    p.birth_date,
    extract(year from p.birth_date)::integer as birth_year,
    p.death_date,
    p.gender as recorded_sex,
    p.race,
    p.ethnicity,
    p.state,
    p.county,
    b.first_event_date,
    b.last_event_date,
    coalesce(b.recorded_event_rows, 0) as recorded_event_rows,
    p.source_batch_id,
    p.source_record_number
from {{ ref('int_patients') }} as p
left join bounds as b on b.patient_key = p.patient_key
