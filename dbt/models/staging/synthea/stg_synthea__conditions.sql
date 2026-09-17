-- Grain: one source condition record (identical records preserved) in the selected input revision.
-- An impossible STOP (earlier than START) is nulled but preserved in source_stop_value (macros/end_date_policy.sql).
with src as (
    {{ snapshot_rows('conditions', 'patient') }}
)

select
    _dataset_id as dataset_id,
    _batch_id as source_batch_id,
    _record_number as source_record_number,
    _row_fingerprint as source_row_fingerprint,
    patient as patient_id,
    encounter as encounter_id,
    start::date as start_date,
    {{ valid_end('start::date', 'stop::date') }} as stop_date,
    stop as source_stop_value,
    {{ end_status('start::date', 'stop::date') }} as stop_status,
    system as source_system,
    code as source_code,
    description as source_description
from src
