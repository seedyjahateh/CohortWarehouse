-- Grain: one source condition record (identical records preserved) in the selected input revision.
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
    stop::date as stop_date,
    system as source_system,
    code as source_code,
    description as source_description
from src
