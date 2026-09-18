{{ config(materialized='table', indexes=[{'columns': ['batch_id'], 'unique': True}],
          post_hook=["analyze {{ this }}"]) }}
-- Grain: one batch that contributes rows to the selected input revision: the latest full snapshot and every
-- scoped batch after it, up to the target revision.
select
    b.batch_id,
    b.dataset_id,
    b.source_revision,
    b.replacement_mode
from {{ source('ops', 'batch') }} as b
inner join {{ ref('stg_ops__selected_revision') }} as rev
    on rev.dataset_id = b.dataset_id
   and b.source_revision >= rev.full_revision
   and b.source_revision <= rev.target_revision
