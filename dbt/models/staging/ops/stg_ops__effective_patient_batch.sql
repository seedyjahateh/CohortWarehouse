{{ config(materialized='table', indexes=[{'columns': ['patient_id'], 'unique': True},
                                         {'columns': ['batch_id', 'patient_id']}],
          post_hook=["analyze {{ this }}"]) }}
-- Grain: one referenced patient id -> the single batch whose rows are in force for that person
-- (Section 9.2: latest scoped batch containing the person, else the latest full snapshot).
--
-- Staging joins this table by equality instead of filtering with `coalesce(...)` inside the predicate.
-- That matters for more than tidiness: the correlated coalesce was opaque to the planner, which estimated
-- one row per staging view and chose nested loops between views (measured: 10+ minutes for 87k encounters
-- at 1,183-person scale). See docs/decisions/0007.
with universe as (
    select p.id as patient_id from {{ source('raw', 'patients') }} as p
        inner join {{ ref('stg_ops__relevant_batch') }} as rb on rb.batch_id = p._batch_id
    union
    select e.patient from {{ source('raw', 'encounters') }} as e
        inner join {{ ref('stg_ops__relevant_batch') }} as rb on rb.batch_id = e._batch_id
    union
    select c.patient from {{ source('raw', 'conditions') }} as c
        inner join {{ ref('stg_ops__relevant_batch') }} as rb on rb.batch_id = c._batch_id
    union
    select m.patient from {{ source('raw', 'medications') }} as m
        inner join {{ ref('stg_ops__relevant_batch') }} as rb on rb.batch_id = m._batch_id
    union
    select o.patient from {{ source('raw', 'observations') }} as o
        inner join {{ ref('stg_ops__relevant_batch') }} as rb on rb.batch_id = o._batch_id
    union
    select s.patient_id from {{ source('ops', 'batch_scope_patient') }} as s
        inner join {{ ref('stg_ops__relevant_batch') }} as rb on rb.batch_id = s.batch_id
)

select
    u.patient_id,
    coalesce(scoped.batch_id, rev.full_batch_id) as batch_id,
    rev.dataset_id,
    scoped.batch_id is not null as from_scoped_batch
from universe as u
cross join {{ ref('stg_ops__selected_revision') }} as rev
left join {{ ref('stg_ops__scoped_patient_batch') }} as scoped
    on scoped.patient_id = u.patient_id
where u.patient_id is not null
