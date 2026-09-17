{% test unique_combination(model, columns) %}
    select {{ columns | join(', ') }}, count(*) as occurrences
    from {{ model }}
    group by {{ columns | join(', ') }}
    having count(*) > 1
{% endtest %}

{% test not_negative(model, column_name) %}
    select * from {{ model }} where {{ column_name }} < 0
{% endtest %}

{#- End must not precede start when both are supplied. -#}
{% test end_not_before_start(model, start_column, end_column) %}
    select * from {{ model }}
    where {{ end_column }} is not null and {{ start_column }} is not null and {{ end_column }} < {{ start_column }}
{% endtest %}

{#- Exactly one row (singleton control tables). -#}
{% test exactly_one_row(model) %}
    select count(*) as row_count from {{ model }} having count(*) <> 1
{% endtest %}
