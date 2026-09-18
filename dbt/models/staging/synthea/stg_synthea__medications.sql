{{
    config(
        materialized='incremental',
        incremental_strategy='append',
        on_schema_change='fail',
        pre_hook=["{{ delete_change_candidate_slice() }}"],
        indexes=[{'columns': ['patient_id']}, {'columns': ['source_code']}],
        post_hook=["analyze {{ this }}"]
    )
}}
-- depends_on: {{ ref('stg_ops__change_candidate') }}
-- Grain: one source medication record (identical records preserved) in the selected input revision.
-- occurrence_ordinal distinguishes identical rows; an impossible STOP is nulled but preserved in
-- source_stop_value (macros/end_date_policy.sql).
with src as (
    {{ snapshot_rows('medications', 'patient', with_ordinal=true) }}
)

select
    _dataset_id as dataset_id,
    _batch_id as source_batch_id,
    _record_number as source_record_number,
    _row_fingerprint as source_row_fingerprint,
    occurrence_ordinal,
    patient as patient_id,
    encounter as encounter_id,
    start::timestamptz as start_at,
    {{ valid_end('start::timestamptz', 'stop::timestamptz') }} as stop_at,
    {{ utc_date('start::timestamptz') }} as start_date,
    {{ utc_date(valid_end('start::timestamptz', 'stop::timestamptz')) }} as stop_date,
    stop as source_stop_value,
    {{ end_status('start::timestamptz', 'stop::timestamptz') }} as stop_status,
    null::text as source_system,
    code as source_code,
    description as source_description,
    {{ parse_numeric('dispenses') }} as dispenses,
    {{ numeric_parse_status('dispenses') }} as dispenses_status,
    {{ parse_numeric('base_cost') }} as base_cost,
    {{ numeric_parse_status('base_cost') }} as base_cost_status,
    {{ parse_numeric('totalcost') }} as total_cost,
    {{ numeric_parse_status('totalcost') }} as total_cost_status
from src
