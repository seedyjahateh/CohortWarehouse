{{ config(materialized='table', indexes=[{'columns': ['patient_id']}, {'columns': ['source_code', 'observation_date']}], post_hook=["analyze {{ this }}"]) }}
-- Grain: one source observation record, including repeated same-time values, in the selected revision.
with src as (
    {{ snapshot_rows('observations', 'patient') }}
)

select
    _dataset_id as dataset_id,
    _batch_id as source_batch_id,
    _record_number as source_record_number,
    _row_fingerprint as source_row_fingerprint,
    patient as patient_id,
    encounter as encounter_id,
    "date"::timestamptz as observed_at,
    {{ utc_date('"date"::timestamptz') }} as observation_date,
    lower(category) as source_category,
    null::text as source_system,
    code as source_code,
    description as source_description,
    value as value_text,
    units as source_unit,
    lower(type) as source_value_type,
    case when lower(type) = 'numeric' then {{ parse_numeric('value') }} end as value_as_number,
    case
        when value is null then 'missing'
        when lower(type) = 'numeric' and value ~ {{ numeric_pattern() }} then 'numeric'
        when lower(type) = 'numeric' then 'invalid'
        else 'text'
    end as value_parse_status
from src
