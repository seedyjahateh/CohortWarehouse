-- Grain: one cohort definition version, with the as-of date and explicit code list it was evaluated with.
with codes as (
    select code_set_id, max(code_set_version) as code_set_version,
           string_agg(omop_vocabulary_id || ' ' || source_code || ' (' || description || ')', '; '
                      order by source_code) as code_list
    from {{ ref('cohort_code_sets') }}
    group by code_set_id
)

select
    d.cohort_id,
    d.definition_version,
    d.cohort_id || ' v' || d.definition_version as definition_label,
    d.label as cohort_label,
    d.short_rule,
    rev.as_of_date,
    rev.as_of_date - d.encounter_lookback_days as encounter_window_start,
    rev.as_of_date - d.measurement_lookback_days as measurement_window_start,
    d.systolic_threshold_exclusive,
    d.min_encounters,
    d.condition_code_set_id,
    cc.code_set_version as condition_code_set_version,
    cc.code_list as condition_codes,
    d.measurement_code_set_id,
    mc.code_set_version as measurement_code_set_version,
    mc.code_list as measurement_codes,
    d.review_status,
    'Descriptive share of eligible synthetic records; not prevalence and not a validated phenotype.'
        as interpretation_note,
    'Synthetic data - demonstration only' as data_label
from {{ ref('cohort_definitions') }} as d
cross join {{ ref('stg_ops__selected_revision') }} as rev
left join codes as cc on cc.code_set_id = d.condition_code_set_id
left join codes as mc on mc.code_set_id = d.measurement_code_set_id
