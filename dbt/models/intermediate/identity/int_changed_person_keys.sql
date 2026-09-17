{{ config(materialized='table', indexes=[{'columns': ['patient_key'], 'unique': True}]) }}
-- depends_on: {{ ref('int_key_registry') }}
-- Grain: one changed person with its stable patient key (resolved after registration, so new people
-- are included). Drives incremental slice deletes and inserts.
select
    c.dataset_id,
    c.patient_id,
    c.change_type,
    k.surrogate_id as patient_key
from {{ ref('int_changed_person') }} as c
inner join {{ source('ops', 'entity_key_map') }} as k
    on k.entity_type = 'patient'
   and k.dataset_id = c.dataset_id
   and k.natural_key = c.patient_id
