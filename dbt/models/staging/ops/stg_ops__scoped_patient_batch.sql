{{ config(materialized='table', indexes=[{'columns': ['patient_id'], 'unique': True}],
          post_hook=["analyze {{ this }}"]) }}
-- Grain: one row per patient covered by a scoped batch after the latest full snapshot;
-- batch_id is the latest such batch (the patient's effective batch).
select distinct on (s.patient_id)
    s.patient_id,
    s.batch_id,
    b.source_revision
from {{ source('ops', 'batch_scope_patient') }} as s
inner join {{ source('ops', 'batch') }} as b
    on b.batch_id = s.batch_id
inner join {{ ref('stg_ops__selected_revision') }} as rev
    on rev.dataset_id = b.dataset_id
   and b.source_revision > rev.full_revision
   and b.source_revision <= rev.target_revision
order by s.patient_id, b.source_revision desc
