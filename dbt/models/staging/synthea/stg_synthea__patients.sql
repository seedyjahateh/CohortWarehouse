{{ config(materialized='table', indexes=[{'columns': ['patient_id'], 'unique': True}], post_hook=["analyze {{ this }}"]) }}
-- Grain: one patient in the selected input revision.
with src as (
    {{ snapshot_rows('patients', 'id') }}
)

select
    _dataset_id as dataset_id,
    _batch_id as source_batch_id,
    _record_number as source_record_number,
    _row_fingerprint as source_row_fingerprint,
    id as patient_id,
    birthdate::date as birth_date,
    deathdate::date as death_date,
    lower(race) as race,
    lower(ethnicity) as ethnicity,
    upper(gender) as gender,
    state,
    county
from src
