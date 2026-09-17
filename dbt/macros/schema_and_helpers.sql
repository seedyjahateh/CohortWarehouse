{#- Use the configured schema name verbatim (stg, int, work_star, ...), never target_custom. -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}{{ target.schema }}{%- else -%}{{ custom_schema_name | trim }}{%- endif -%}
{%- endmacro %}


{#- Rows of one raw file that belong to the selected input revision (Section 9.2).
    For each patient the effective batch is the latest scoped batch whose declared scope contains the
    patient, otherwise the latest full snapshot. Rows of superseded batches are never selected, so a
    patient in scope but absent from the scoped batch has been removed. -#}
{% macro snapshot_rows(file_key, patient_column) %}
    select r.*
    from {{ source('raw', file_key) }} as r
    cross join {{ ref('stg_ops__selected_revision') }} as rev
    left join {{ ref('stg_ops__scoped_patient_batch') }} as scoped
        on scoped.patient_id = r.{{ patient_column }}
    where r._dataset_id = rev.dataset_id
      and r._batch_id = coalesce(scoped.batch_id, rev.full_batch_id)
{% endmacro %}


{#- Numeric parsing that distinguishes missing, invalid and zero (STG-02). -#}
{% macro numeric_pattern() -%}
    '^\s*[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]{1,3})?\s*$'
{%- endmacro %}

{% macro parse_numeric(column) -%}
    case when {{ column }} ~ {{ numeric_pattern() }} then trim({{ column }})::numeric end
{%- endmacro %}

{% macro numeric_parse_status(column) -%}
    case
        when {{ column }} is null then 'missing'
        when {{ column }} ~ {{ numeric_pattern() }} then 'numeric'
        else 'invalid'
    end
{%- endmacro %}

{% macro utc_date(timestamptz_column) -%}
    ({{ timestamptz_column }} at time zone 'UTC')::date
{%- endmacro %}

{% macro date_key(date_column) -%}
    coalesce(to_char({{ date_column }}, 'YYYYMMDD')::integer, 0)
{%- endmacro %}

{#- Pseudonymous person key for published marts: never the source UUID. -#}
{% macro pseudonym(dataset_column, id_column) -%}
    left(encode(sha256(convert_to({{ dataset_column }} || ':' || {{ id_column }}, 'UTF8')), 'hex'), 20)
{%- endmacro %}

{% macro as_of_date() -%}
    (select as_of_date from {{ ref('stg_ops__selected_revision') }})
{%- endmacro %}

{#- Run context comes from environment variables, not --vars: changing a var forces dbt to re-parse the
    whole project, while env_var changes only re-parse the files that use them. -#}
{% macro run_id() -%}
    {%- set value = env_var('CW_RUN_ID', '__no_run__') -%}
    {%- if "'" in value or "\\" in value -%}
        {{ exceptions.raise_compiler_error("unsafe CW_RUN_ID") }}
    {%- endif -%}
    {{- value -}}
{%- endmacro %}

{% macro git_sha() -%}
    {{- env_var('CW_GIT_SHA', 'unknown') | replace("'", "") -}}
{%- endmacro %}

{#- Keep planner statistics current for every materialised relation (views are skipped). -#}
{% macro analyze_relation() -%}
    {%- if config.get('materialized') in ('table', 'incremental', 'seed') -%}
        analyze {{ this }}
    {%- else -%}
        select 1
    {%- endif -%}
{%- endmacro %}

{#- Recovery drill: make one named model fail after its slice delete has run. -#}
{% macro maybe_inject_failure() -%}
    {%- if env_var('CW_INJECT_FAILURE_MODEL', '') == this.identifier -%}
        select 1 / 0 as injected_failure
    {%- else -%}
        select 1
    {%- endif -%}
{%- endmacro %}
