{{
    config(
        materialized='incremental',
        incremental_strategy='append',
        on_schema_change='fail',
        pre_hook=["{{ delete_changed_person_slice() }}"],
        indexes=[{'columns': ['encounter_key'], 'unique': True}, {'columns': ['patient_key']},
                 {'columns': ['encounter_id']}, {'columns': ['start_date']}]
    )
}}
-- depends_on: {{ ref('int_key_registry') }}
-- depends_on: {{ ref('int_changed_person') }}
-- depends_on: {{ ref('int_changed_person_keys') }}
-- Grain: one source encounter whose patient exists (orphans go to the exclusion ledger, never Unknown).
-- Incremental by changed person. Organization-id set changes force a full refresh (pipeline.start_run).
select
    k.surrogate_id as encounter_key,
    pk.surrogate_id as patient_key,
    case when o.organization_id is not null then ok.surrogate_id else 0 end as organization_key,
    case
        when e.organization_id is null then 'absent'
        when o.organization_id is null then 'unresolved'
        else 'linked'
    end as organization_link_status,
    coalesce(tk.surrogate_id, 0) as encounter_type_key,
    ec.source_class is not null as encounter_class_accepted,
    round((extract(epoch from (e.stop_at - e.start_at)) / 60.0)::numeric, 2) as duration_minutes,
    e.*
from {{ ref('stg_synthea__encounters') }} as e
inner join {{ ref('stg_synthea__patients') }} as p
    on p.dataset_id = e.dataset_id and p.patient_id = e.patient_id
left join {{ ref('stg_synthea__organizations') }} as o
    on o.dataset_id = e.dataset_id and o.organization_id = e.organization_id
left join {{ ref('encounter_classes') }} as ec
    on ec.source_class = e.encounter_class
{{ key_lookup('encounter', 'k', 'e.dataset_id', 'e.encounter_id') }}
{{ key_lookup('patient', 'pk', 'e.dataset_id', 'e.patient_id') }}
{{ key_lookup('organization', 'ok', 'e.dataset_id', 'e.organization_id') }}
{{ key_lookup('encounter_type', 'tk', 'e.dataset_id', 'e.encounter_class') }}
{% if is_incremental() %}
where e.patient_id in {{ changed_person_subquery('patient_id') }}
{% endif %}
