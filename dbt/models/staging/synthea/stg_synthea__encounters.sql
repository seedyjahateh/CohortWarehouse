{{
    config(
        materialized='incremental',
        incremental_strategy='append',
        on_schema_change='fail',
        pre_hook=["{{ delete_change_candidate_slice() }}"],
        indexes=[{'columns': ['encounter_id'], 'unique': True}, {'columns': ['patient_id']},
                 {'columns': ['start_date']}],
        post_hook=["analyze {{ this }}"]
    )
}}
-- depends_on: {{ ref('stg_ops__change_candidate') }}
-- Grain: one source encounter in the selected input revision. Timestamps normalised to UTC.
-- An impossible STOP (earlier than START) is nulled but preserved in source_stop_value (macros/end_date_policy.sql).
with src as (
    {{ snapshot_rows('encounters', 'patient') }}
)

select
    _dataset_id as dataset_id,
    _batch_id as source_batch_id,
    _record_number as source_record_number,
    _row_fingerprint as source_row_fingerprint,
    id as encounter_id,
    patient as patient_id,
    organization as organization_id,
    provider as provider_id,
    payer as payer_id,
    start::timestamptz as start_at,
    {{ valid_end('start::timestamptz', 'stop::timestamptz') }} as stop_at,
    {{ utc_date('start::timestamptz') }} as start_date,
    {{ utc_date(valid_end('start::timestamptz', 'stop::timestamptz')) }} as stop_date,
    stop as source_stop_value,
    {{ end_status('start::timestamptz', 'stop::timestamptz') }} as stop_status,
    lower(encounterclass) as encounter_class,
    code as encounter_code,
    description as encounter_description,
    {{ parse_numeric('base_encounter_cost') }} as base_encounter_cost,
    {{ numeric_parse_status('base_encounter_cost') }} as base_encounter_cost_status,
    {{ parse_numeric('total_claim_cost') }} as total_claim_cost,
    {{ numeric_parse_status('total_claim_cost') }} as total_claim_cost_status,
    reasoncode as reason_code
from src
