{{
    config(
        materialized='incremental',
        incremental_strategy='append',
        on_schema_change='fail',
        pre_hook=["{{ delete_changed_person_slice() }}"],
        indexes=[{'columns': ['event_key'], 'unique': True}, {'columns': ['patient_key']},
                 {'columns': ['source_event_key']}, {'columns': ['source_vocabulary_id', 'source_code', 'observation_date']}]
    )
}}
-- depends_on: {{ ref('int_key_registry') }}
-- depends_on: {{ ref('int_changed_person') }}
-- depends_on: {{ ref('int_changed_person_keys') }}
-- Grain: one source observation record with a valid patient (repeated same-time values preserved).
-- Incremental by changed person.
with keyed as (
    {{ keyed_clinical_events('int_observation_events', 'observation') }}
)

select
    keyed.*,
    coalesce(uk.surrogate_id, 0) as unit_key
from keyed
{{ key_lookup('unit', 'uk', 'keyed.dataset_id', 'keyed.source_unit') }}
