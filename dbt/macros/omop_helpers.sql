{% macro fixed_concept(role) -%}
    (select concept_id from {{ ref('int_omop_reference_concepts') }}
     where concept_role = 'fixed:{{ role }}' and invalid_reason is null)
{%- endmacro %}

{#- Timestamp without time zone in UTC, as OMOP datetime columns are zone-less. -#}
{% macro omop_datetime(timestamptz_column) -%}
    ({{ timestamptz_column }} at time zone 'UTC')
{%- endmacro %}

{#- Incremental OMOP event table config shared by the clinical domain tables. -#}
{% macro omop_event_where(destination) -%}
    where destination_table = '{{ destination }}'
      and person_included
    {% if is_incremental() -%}
      and person_id in (select patient_key from {{ ref('int_changed_person_keys') }})
    {%- endif %}
{%- endmacro %}
