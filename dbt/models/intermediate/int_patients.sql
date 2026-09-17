{{ config(indexes=[{'columns': ['patient_key'], 'unique': True}, {'columns': ['patient_id']}]) }}
-- depends_on: {{ ref('int_key_registry') }}
-- Grain: one patient in the selected revision, with stable key and pseudonymous id.
select
    k.surrogate_id as patient_key,
    {{ pseudonym('p.dataset_id', 'p.patient_id') }} as patient_pseudo_id,
    p.*
from {{ ref('stg_synthea__patients') }} as p
{{ key_lookup('patient', 'k', 'p.dataset_id', 'p.patient_id') }}
