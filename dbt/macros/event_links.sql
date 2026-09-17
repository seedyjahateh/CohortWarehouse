{#- Shared encounter-link resolution for clinical events (STG-03):
    absent       -> no encounter supplied (null link)
    unresolved   -> supplied encounter not in the revision (link nulled, event retained, ledgered)
    wrong_person -> supplied encounter belongs to another person (BLOCKING test)
    linked       -> same person -#}
{% macro keyed_clinical_events(events_model, entity_type) %}
select
    ek.surrogate_id as event_key,
    pk.surrogate_id as patient_key,
    ck.surrogate_id as clinical_code_key,
    case when enc.patient_id = e.patient_id then enc.encounter_key end as encounter_key,
    case
        when e.encounter_id is null then 'absent'
        when enc.encounter_id is null then 'unresolved'
        when enc.patient_id <> e.patient_id then 'wrong_person'
        else 'linked'
    end as encounter_link_status,
    e.*
from {{ ref(events_model) }} as e
left join {{ ref('int_encounters') }} as enc
    on enc.dataset_id = e.dataset_id and enc.encounter_id = e.encounter_id
{{ key_lookup(entity_type, 'ek', 'e.dataset_id', 'e.source_event_key') }}
{{ key_lookup('patient', 'pk', 'e.dataset_id', 'e.patient_id') }}
{{ key_lookup('clinical_code', 'ck', 'e.dataset_id', 'e.clinical_code_natural_key') }}
where e.patient_exists
{% if is_incremental() %}
  and e.patient_id in {{ changed_person_subquery('patient_id') }}
{% endif %}
{% endmacro %}
