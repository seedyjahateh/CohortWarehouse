{{
    config(
        materialized='incremental',
        incremental_strategy='append',
        on_schema_change='fail',
        pre_hook=["{{ delete_changed_person_slice() }}"],
        indexes=[{'columns': ['event_key'], 'unique': True}, {'columns': ['patient_key']},
                 {'columns': ['source_event_key']}]
    )
}}
-- depends_on: {{ ref('int_key_registry') }}
-- depends_on: {{ ref('int_changed_person') }}
-- depends_on: {{ ref('int_changed_person_keys') }}
-- Grain: one source medication record with a valid patient. Incremental by changed person.
{{ keyed_clinical_events('int_medication_events', 'medication') }}
