{{ config(materialized='table', post_hook=["analyze {{ this }}"]) }}
-- Grain: exactly one row, the input revision selected by env CW_RUN_ID.
-- A table (not a view) so every downstream plan sees real statistics for this control row.
with run as (
    select run_id, dataset_id, target_batch_id, target_revision, as_of_date, mode
    from {{ source('ops', 'pipeline_run') }}
    where run_id = '{{ run_id() }}'
),

eligible_batches as (
    select b.batch_id, b.dataset_id, b.source_revision, b.replacement_mode, b.delivered_at
    from {{ source('ops', 'batch') }} as b
    inner join run as r
        on r.dataset_id = b.dataset_id
       and b.source_revision <= r.target_revision
),

latest_full as (
    select distinct on (dataset_id) dataset_id, batch_id, source_revision
    from eligible_batches
    where replacement_mode = 'full'
    order by dataset_id, source_revision desc
)

select
    r.run_id,
    r.dataset_id,
    r.mode as run_mode,
    r.target_batch_id,
    r.target_revision,
    r.as_of_date,
    f.batch_id as full_batch_id,
    f.source_revision as full_revision,
    t.delivered_at as target_delivered_at
from run as r
inner join latest_full as f on f.dataset_id = r.dataset_id
inner join eligible_batches as t on t.batch_id = r.target_batch_id
