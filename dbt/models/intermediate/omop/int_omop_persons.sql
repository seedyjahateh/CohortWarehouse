{{
    config(
        materialized='incremental',
        incremental_strategy='append',
        on_schema_change='fail',
        pre_hook=["{{ delete_changed_person_slice() }}"],
        indexes=[{'columns': ['patient_key'], 'unique': True}]
    )
}}
-- depends_on: {{ ref('int_changed_person_keys') }}
-- Grain: one patient of the selected revision with the project's OMOP population decision and inferred
-- observation period: earliest supported event to latest supported boundary, clipped to D and death.
-- The inferred span does NOT establish continuous coverage (docs/omop-scope.md).
-- Incremental by changed person; a change of D forces a full refresh (pipeline.start_run).
with rev as (
    select as_of_date from {{ ref('stg_ops__selected_revision') }}
),

people as (
    select * from {{ ref('int_patients') }}
    {{ changed_person_filter() }}
),

supported_events as (
    select e.patient_key, e.start_date, coalesce(e.stop_date, e.start_date) as end_date
    from {{ ref('int_encounters') }} as e
    inner join people as p on p.patient_key = e.patient_key

    union all

    select p.patient_key, c.start_date, coalesce(c.end_date, c.start_date)
    from {{ ref('int_omop_event_candidates') }} as c
    inner join people as p
        on p.dataset_id = c.dataset_id and p.patient_id = c.patient_id
    where c.proposed_destination is not null
      and c.routing_exclusion_reason is null
),

per_person as (
    select
        patient_key,
        min(start_date) as first_event_date,
        max(greatest(start_date, end_date)) as last_event_date,
        count(*) as supported_event_rows
    from supported_events
    group by patient_key
)

select
    p.patient_key,
    p.dataset_id,
    p.death_date,
    rev.as_of_date,
    pp.first_event_date,
    pp.last_event_date,
    coalesce(pp.supported_event_rows, 0) as supported_event_rows,
    pp.first_event_date as observation_period_start_date,
    least(pp.last_event_date, rev.as_of_date, p.death_date) as observation_period_end_date,
    case
        when pp.patient_key is null then 'no_supported_events'
        when pp.first_event_date > least(rev.as_of_date, p.death_date) then 'first_event_after_as_of_or_death'
    end as exclusion_reason,
    coalesce(pp.patient_key is not null and pp.first_event_date <= least(rev.as_of_date, p.death_date), false)
        as is_included
from people as p
cross join rev
left join per_person as pp
    on pp.patient_key = p.patient_key
