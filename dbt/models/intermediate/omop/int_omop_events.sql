{{
    config(
        materialized='incremental',
        incremental_strategy='append',
        on_schema_change='fail',
        pre_hook=["{{ delete_changed_person_slice('person_id') }}"],
        indexes=[{'columns': ['person_id']}, {'columns': ['destination_table']}]
    )
}}
-- depends_on: {{ ref('int_key_registry') }}
-- depends_on: {{ ref('int_changed_person') }}
-- depends_on: {{ ref('int_changed_person_keys') }}
-- Grain: one routed OMOP clinical row = (source event, destination table, target concept, mapping ordinal).
-- OMOP ids come from the registry (Section 8.4.6): a mapping revision may change them, person ids never.
select
    ok.surrogate_id as omop_event_id,
    p.patient_key as person_id,
    coalesce(op.is_included, false) as person_included,
    case when enc.patient_id = c.patient_id then enc.encounter_key end as visit_occurrence_id,
    case
        when c.encounter_id is null then 'absent'
        when enc.encounter_id is null then 'unresolved'
        when enc.patient_id <> c.patient_id then 'wrong_person'
        else 'linked'
    end as visit_link_status,
    c.proposed_destination as destination_table,
    c.end_date is null and c.proposed_destination = 'drug_exposure' as end_date_imputed,
    c.*
from {{ ref('int_omop_event_candidates') }} as c
inner join {{ ref('int_patients') }} as p
    on p.dataset_id = c.dataset_id and p.patient_id = c.patient_id
left join {{ ref('int_omop_persons') }} as op
    on op.patient_key = p.patient_key
left join {{ ref('int_encounters') }} as enc
    on enc.dataset_id = c.dataset_id and enc.encounter_id = c.encounter_id
{{ key_lookup('omop_event', 'ok', 'c.dataset_id', 'c.omop_event_natural_key') }}
where c.proposed_destination is not null
  and c.routing_exclusion_reason is null
{% if is_incremental() %}
  and c.patient_id in {{ changed_person_subquery('patient_id') }}
{% endif %}
