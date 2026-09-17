{#- Candidate natural keys per registered entity type (used by int_key_registry pre-hooks). -#}
{% macro key_registration_query(entity) -%}
    {%- set changed -%}(select patient_id from {{ ref('int_changed_person') }}){%- endset -%}
    {%- if entity == 'patient' -%}
        select dataset_id, patient_id as natural_key from {{ ref('stg_synthea__patients') }}
    {%- elif entity == 'organization' -%}
        select dataset_id, organization_id as natural_key from {{ ref('stg_synthea__organizations') }}
    {%- elif entity == 'encounter_type' -%}
        select rev.dataset_id, s.source_class as natural_key
        from {{ ref('encounter_classes') }} as s
        cross join {{ ref('stg_ops__selected_revision') }} as rev
        union
        select dataset_id, encounter_class from {{ ref('stg_synthea__encounters') }}
    {%- elif entity == 'encounter' -%}
        select e.dataset_id, e.encounter_id as natural_key
        from {{ ref('stg_synthea__encounters') }} as e
        inner join {{ ref('stg_synthea__patients') }} as p
            on p.dataset_id = e.dataset_id and p.patient_id = e.patient_id
        where e.patient_id in {{ changed }}
    {%- elif entity in ('condition', 'medication', 'observation') -%}
        select dataset_id, source_event_key as natural_key
        from {{ ref('int_' ~ entity ~ '_events') }}
        where patient_exists and patient_id in {{ changed }}
    {%- elif entity == 'clinical_code' -%}
        {%- for f in ['condition', 'medication', 'observation'] %}
        select dataset_id, clinical_code_natural_key as natural_key
        from {{ ref('int_' ~ f ~ '_events') }}
        where patient_exists and patient_id in {{ changed }}
        {% if not loop.last %}union{% endif %}
        {%- endfor -%}
    {%- elif entity == 'unit' -%}
        select dataset_id, source_unit as natural_key
        from {{ ref('int_observation_events') }}
        where source_unit is not null and patient_exists and patient_id in {{ changed }}
    {%- elif entity == 'omop_event' -%}
        select dataset_id, omop_event_natural_key as natural_key
        from {{ ref('int_omop_event_candidates') }}
        where proposed_destination is not null
          and routing_exclusion_reason is null
          and patient_id in {{ changed }}
    {%- else -%}
        {{ exceptions.raise_compiler_error("unknown registry entity " ~ entity) }}
    {%- endif -%}
{%- endmacro %}
