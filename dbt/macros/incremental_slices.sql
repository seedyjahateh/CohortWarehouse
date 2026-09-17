{#- Changed-person slice replacement (Section 9.2, step 5).

    Incremental person-linked models use incremental_strategy='append' plus this transactional pre-hook.
    dbt-postgres runs pre-hooks, the insert and post-hooks inside one transaction, so the delete of
    a person's old slice and the insert of the complete replacement commit together or not at all.
    People who now have zero rows are covered because the delete is driven by the changed-person
    set, not by the rows being inserted.

    via='patient_key' uses stable keys (int_changed_person_keys, available after key registration);
    via='patient_id' uses source ids (int_changed_person) for models built before registration. -#}
{% macro changed_person_subquery(via='patient_key') -%}
    {%- if via == 'patient_id' -%}
        (select patient_id from {{ ref('int_changed_person') }})
    {%- else -%}
        (select patient_key from {{ ref('int_changed_person_keys') }})
    {%- endif -%}
{%- endmacro %}

{% macro delete_changed_person_slice(person_column='patient_key', via='patient_key') -%}
    {%- if is_incremental() -%}
        delete from {{ this }} where {{ person_column }} in {{ changed_person_subquery(via) }}
    {%- else -%}
        select 1
    {%- endif -%}
{%- endmacro %}

{% macro changed_person_filter(person_column='patient_key', via='patient_key') -%}
    {%- if is_incremental() -%}
        where {{ person_column }} in {{ changed_person_subquery(via) }}
    {%- endif -%}
{%- endmacro %}


{#- Stable surrogate keys (Section 8.4). Only natural keys missing from the registry are inserted, so
    the sequence is not consumed by already-registered rows. ON CONFLICT covers concurrent writers. -#}
{% macro register_natural_keys(entity_type, query) -%}
    insert into {{ source('ops', 'entity_key_map') }} (entity_type, dataset_id, natural_key, first_run_id)
    select '{{ entity_type }}', q.dataset_id, q.natural_key, '{{ run_id() }}'
    from (
        select distinct dataset_id, natural_key from ({{ query }}) as candidates
    ) as q
    where not exists (
        select 1 from {{ source('ops', 'entity_key_map') }} as m
        where m.entity_type = '{{ entity_type }}'
          and m.dataset_id = q.dataset_id
          and m.natural_key = q.natural_key
    )
    order by q.dataset_id, q.natural_key
    on conflict (entity_type, dataset_id, natural_key) do nothing
{%- endmacro %}

{% macro key_lookup(entity_type, alias, dataset_expr, natural_key_expr) -%}
    left join {{ source('ops', 'entity_key_map') }} as {{ alias }}
        on {{ alias }}.entity_type = '{{ entity_type }}'
       and {{ alias }}.dataset_id = {{ dataset_expr }}
       and {{ alias }}.natural_key = {{ natural_key_expr }}
{%- endmacro %}
