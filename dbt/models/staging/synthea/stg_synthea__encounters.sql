-- Grain: one source encounter in the selected input revision. Timestamps normalised to UTC.
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
    stop::timestamptz as stop_at,
    {{ utc_date('start::timestamptz') }} as start_date,
    {{ utc_date('stop::timestamptz') }} as stop_date,
    lower(encounterclass) as encounter_class,
    code as encounter_code,
    description as encounter_description,
    {{ parse_numeric('base_encounter_cost') }} as base_encounter_cost,
    {{ numeric_parse_status('base_encounter_cost') }} as base_encounter_cost_status,
    {{ parse_numeric('total_claim_cost') }} as total_claim_cost,
    {{ numeric_parse_status('total_claim_cost') }} as total_claim_cost_status,
    reasoncode as reason_code
from src
