-- Grain: one source medication record (identical records preserved) in the selected input revision.
with src as (
    {{ snapshot_rows('medications', 'patient') }}
)

select
    _dataset_id as dataset_id,
    _batch_id as source_batch_id,
    _record_number as source_record_number,
    _row_fingerprint as source_row_fingerprint,
    patient as patient_id,
    encounter as encounter_id,
    start::timestamptz as start_at,
    stop::timestamptz as stop_at,
    {{ utc_date('start::timestamptz') }} as start_date,
    {{ utc_date('stop::timestamptz') }} as stop_date,
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
