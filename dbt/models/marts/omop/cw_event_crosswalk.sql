{{
    config(
        materialized='incremental',
        incremental_strategy='append',
        on_schema_change='fail',
        pre_hook=["{{ delete_changed_person_slice('person_id') }}"],
        indexes=[{'columns': ['destination_table', 'omop_row_id']}, {'columns': ['source_event_key']}, {'columns': ['person_id']}]
    )
}}
-- depends_on: {{ ref('int_changed_person_keys') }}
-- NOT a CDM table (cw_ prefix). Grain: one OMOP row produced for an included person, with its source
-- event, star fact key and mapping decision (MOD-02, DOC-04). Custom audit fields live here, never in
-- official CDM tables.
select
    'visit_occurrence' as destination_table,
    e.encounter_key as omop_row_id,
    e.patient_key as person_id,
    'encounters' as source_file,
    e.source_row_fingerprint as source_event_key,
    e.encounter_key as star_fact_key,
    null::integer as target_concept_id,
    null::integer as source_concept_id,
    'visit_class_seed' as mapping_status,
    1 as mapping_ordinal,
    null::integer as value_as_concept_id,
    e.stop_date is null as end_date_imputed,
    e.source_batch_id,
    e.source_record_number
from {{ ref('int_encounters') }} as e
inner join {{ ref('int_omop_persons') }} as op on op.patient_key = e.patient_key and op.is_included
{% if is_incremental() %}
where e.patient_key in (select patient_key from {{ ref('int_changed_person_keys') }})
{% endif %}

union all

select
    o.destination_table,
    o.omop_event_id,
    o.person_id,
    o.source_file,
    o.source_event_key,
    coalesce(c.event_key, m.event_key, ob.event_key) as star_fact_key,
    o.target_concept_id,
    o.source_concept_id,
    o.mapping_status,
    o.mapping_ordinal,
    o.value_as_concept_id,
    o.end_date_imputed,
    o.source_batch_id,
    o.source_record_number
from {{ ref('int_omop_events') }} as o
left join {{ ref('int_conditions') }} as c
    on o.source_file = 'conditions' and c.dataset_id = o.dataset_id and c.source_event_key = o.source_event_key
left join {{ ref('int_medications') }} as m
    on o.source_file = 'medications' and m.dataset_id = o.dataset_id and m.source_event_key = o.source_event_key
left join {{ ref('int_observations') }} as ob
    on o.source_file = 'observations' and ob.dataset_id = o.dataset_id and ob.source_event_key = o.source_event_key
where o.person_included
{% if is_incremental() %}
  and o.person_id in (select patient_key from {{ ref('int_changed_person_keys') }})
{% endif %}
