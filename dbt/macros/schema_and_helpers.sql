{#- Use the configured schema name verbatim (stg, int, work_star, ...), never target_custom. -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}{{ target.schema }}{%- else -%}{{ custom_schema_name | trim }}{%- endif -%}
{%- endmacro %}


{#- Rows of one raw file that belong to the selected input revision (Section 9.2).
    Each patient's effective batch is resolved once in stg_ops__effective_patient_batch; this is a plain
    equi-join so the planner has real statistics on both sides. Rows of superseded batches are never
    selected, so a patient in scope but absent from the scoped batch has been removed. -#}
{% macro snapshot_rows(file_key, patient_column, with_ordinal=false) %}
    select
        r.*
        {%- if with_ordinal %},
        -- Occurrence ordinal for rows with no durable source id (Section 8.4.3). Computed here, where the
        -- window is evaluated once per run, so downstream person-slice models can filter by an indexed
        -- patient lookup instead of forcing the window over every row (measured: 55s -> ~1s per slice).
        row_number() over (
            partition by r._dataset_id, r.{{ patient_column }}, r._row_fingerprint
            order by r._batch_id, r._record_number
        ) as occurrence_ordinal
        {%- endif %}
    from {{ source('raw', file_key) }} as r
    inner join {{ ref('stg_ops__effective_patient_batch') }} as eff
        on eff.patient_id = r.{{ patient_column }}
       and eff.batch_id = r._batch_id
    {%- if is_incremental() %}
    inner join {{ ref('stg_ops__change_candidate') }} as cc
        on cc.patient_id = r.{{ patient_column }}
    {%- endif %}
{% endmacro %}


{#- Staging person slices: only change candidates are rebuilt (stg_ops__change_candidate). -#}
{% macro delete_change_candidate_slice(person_column='patient_id') -%}
    {%- if is_incremental() -%}
        delete from {{ this }}
        where {{ person_column }} in (select patient_id from {{ ref('stg_ops__change_candidate') }})
    {%- else -%}
        select 1
    {%- endif -%}
{%- endmacro %}


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
