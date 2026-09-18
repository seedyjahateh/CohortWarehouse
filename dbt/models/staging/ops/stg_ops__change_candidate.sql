{{ config(materialized='table', indexes=[{'columns': ['patient_id'], 'unique': True}],
          post_hook=["analyze {{ this }}"]) }}
-- Grain: one patient whose source rows could possibly differ from the last built candidate state.
--
-- Only people named by a scoped delivery can change (Section 9.2.3: absent rows are removals only within the
-- declared replacement scope), so fingerprinting and staging do not need to touch the whole population on
-- every incremental run. The narrowing is abandoned - every patient becomes a candidate - whenever it cannot
-- be proven safe: a full refresh, no previous build, a full snapshot among the new batches, or a target
-- revision at/behind the built one (historical rebuild).
with rev as (
    select * from {{ ref('stg_ops__selected_revision') }}
),

built as (
    select b.source_revision
    from {{ source('ops', 'build_state') }} as b
    inner join rev on rev.dataset_id = b.dataset_id
),

new_batches as (
    select b.batch_id, b.replacement_mode
    from {{ source('ops', 'batch') }} as b
    cross join rev
    where b.dataset_id = rev.dataset_id
      and b.source_revision > (select coalesce(max(source_revision), -1) from built)
      and b.source_revision <= rev.target_revision
),

mode as (
    select
        {% if flags.FULL_REFRESH %}
        false as narrow
        {% else %}
        (select count(*) from built) = 1
        and not exists (select 1 from new_batches where replacement_mode = 'full')
        and (select max(source_revision) from built) <= (select target_revision from rev)
            as narrow
        {% endif %}
)

select patient_id, false as narrowed
from {{ ref('stg_ops__effective_patient_batch') }}
cross join mode
where not mode.narrow

union

select s.patient_id, true
from {{ source('ops', 'batch_scope_patient') }} as s
inner join new_batches as nb on nb.batch_id = s.batch_id
cross join mode
where mode.narrow

union

-- People an unfinished attempt may have half-written (Section 9.2.6).
select p.patient_id, true
from {{ source('ops', 'pending_person') }} as p
cross join rev
cross join mode
where mode.narrow and p.dataset_id = rev.dataset_id
