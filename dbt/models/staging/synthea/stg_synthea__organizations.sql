{{ config(materialized='table', indexes=[{'columns': ['organization_id'], 'unique': True}], post_hook=["analyze {{ this }}"]) }}
-- Grain: one organization in the complete reference snapshot delivered with the target batch.
select
    r._dataset_id as dataset_id,
    r._batch_id as source_batch_id,
    r._record_number as source_record_number,
    r.id as organization_id,
    r.name as organization_name,
    r.city,
    r.state
from {{ source('raw', 'organizations') }} as r
inner join {{ ref('stg_ops__selected_revision') }} as rev
    on r._batch_id = rev.target_batch_id
