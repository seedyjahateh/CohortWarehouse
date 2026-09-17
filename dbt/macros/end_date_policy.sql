{#- Impossible end values (STOP earlier than START) are a known source defect (Synthea v3.3.0 medications,
    profiled 2026-09-17: 108 of 77,303 rows). The event itself is retained; only the unusable end value is
    nulled, its original text is preserved, and the record is listed in the exclusion ledger
    (`data_quality` / `stop_before_start_nulled`) and counted in bi_data_profile. Nothing is dropped silently
    and no end value is invented in the star. -#}
{% macro valid_end(start_expr, stop_expr) -%}
    case when {{ stop_expr }} < {{ start_expr }} then null else {{ stop_expr }} end
{%- endmacro %}

{% macro end_status(start_expr, stop_expr) -%}
    case
        when {{ stop_expr }} is null then 'absent'
        when {{ stop_expr }} < {{ start_expr }} then 'stop_before_start_nulled'
        else 'valid'
    end
{%- endmacro %}
