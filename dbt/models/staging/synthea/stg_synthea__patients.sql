{{
    config(
        materialized='incremental',
        incremental_strategy='append',
        on_schema_change='fail',
        pre_hook=["{{ delete_change_candidate_slice() }}"],
        indexes=[{'columns': ['patient_id'], 'unique': True}],
        post_hook=["analyze {{ this }}"]
    )
}}
-- depends_on: {{ ref('stg_ops__change_candidate') }}
-- Grain: one patient in the selected input revision. Rebuilt only for change candidates.
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
