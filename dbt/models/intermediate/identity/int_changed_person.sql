{{
    config(
        materialized='table',
        indexes=[{'columns': ['patient_id']}],
        post_hook=[
            "insert into {{ source('ops', 'pending_person') }} (dataset_id, patient_id, run_id)
             select dataset_id, patient_id, '{{ run_id() }}' from {{ this }}
             on conflict (dataset_id, patient_id) do update
                set run_id = excluded.run_id, added_at = now()"
        ]
    )
}}
-- Grain: one patient whose slices must be rebuilt in this run.
-- Compared with the last successfully BUILT candidate state (plus people left pending by an
-- unfinished attempt), not with the published release: see docs/decisions/0003.
-- The post-hook records the set as pending; the CLI clears it only after the whole build succeeds.
with rev as (
    select dataset_id from {{ ref('stg_ops__selected_revision') }}
),

current_state as (
    select dataset_id, patient_id, person_fingerprint from {{ ref('int_person_fingerprint') }}
),

built_state as (
    select b.dataset_id, b.patient_id, b.person_fingerprint
    from {{ source('ops', 'person_state_built') }} as b
    inner join rev on rev.dataset_id = b.dataset_id
),

pending as (
    select p.dataset_id, p.patient_id
    from {{ source('ops', 'pending_person') }} as p
    inner join rev on rev.dataset_id = p.dataset_id
)

{% if flags.FULL_REFRESH %}
select dataset_id, patient_id, 'full_refresh' as change_type from current_state
union
select dataset_id, patient_id, 'full_refresh' from built_state
{% else %}
, diff as (
    select
        coalesce(c.dataset_id, b.dataset_id) as dataset_id,
        coalesce(c.patient_id, b.patient_id) as patient_id,
        case
            when b.patient_id is null then 'new'
            when c.patient_id is null then 'removed'
            when c.person_fingerprint <> b.person_fingerprint then 'changed'
        end as change_type
    from current_state as c
    full outer join built_state as b
        on b.dataset_id = c.dataset_id and b.patient_id = c.patient_id
)

select dataset_id, patient_id, change_type from diff where change_type is not null
union all
select p.dataset_id, p.patient_id, 'pending_retry'
from pending as p
where not exists (
    select 1 from diff as d
    where d.change_type is not null and d.dataset_id = p.dataset_id and d.patient_id = p.patient_id
)
{% endif %}
