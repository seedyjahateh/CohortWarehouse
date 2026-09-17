-- Grain: one input category (source file) plus one row for the cohort code sets (MAP-06).
-- Numerator: distinct source events with >= 1 valid, supported standard mapping (fan-out never inflates it).
-- Denominator: all accepted events with a valid patient in that category, including routing exceptions.
with per_event as (
    select
        source_file,
        source_event_key,
        bool_or(has_valid_supported_mapping) as is_mapped,
        bool_or(routing_exclusion_reason is not null) as has_routing_exclusion,
        max(source_vocabulary_id || '|' || source_code) as code_key
    from {{ ref('int_omop_event_candidates') }}
    group by source_file, source_event_key
),

by_category as (
    select
        source_file as category,
        count(*) as accepted_events,
        count(*) filter (where is_mapped) as mapped_events,
        count(*) filter (where not is_mapped and not has_routing_exclusion) as retained_unmapped_events,
        count(*) filter (where has_routing_exclusion) as routing_excluded_events,
        count(distinct code_key) as distinct_codes,
        count(distinct code_key) filter (where is_mapped) as distinct_codes_mapped
    from per_event
    group by source_file
),

cohort_codes as (
    select
        'cohort code sets' as category,
        count(*) as accepted_events,
        count(*) filter (where m.target_concept_id is not null and m.target_concept_id <> 0) as mapped_events,
        0::bigint as retained_unmapped_events,
        0::bigint as routing_excluded_events,
        count(*) as distinct_codes,
        count(*) filter (where m.target_concept_id is not null and m.target_concept_id <> 0) as distinct_codes_mapped
    from {{ ref('cohort_code_sets') }} as cs
    left join (
        select source_vocabulary_id, source_code, max(target_concept_id) as target_concept_id
        from {{ ref('int_concept_map') }} group by 1, 2
    ) as m
        on m.source_vocabulary_id = cs.omop_vocabulary_id and m.source_code = cs.source_code
)

select
    category,
    accepted_events,
    mapped_events,
    retained_unmapped_events,
    routing_excluded_events,
    round(100.0 * mapped_events / nullif(accepted_events, 0), 2) as event_weighted_coverage_pct,
    distinct_codes,
    distinct_codes_mapped,
    round(100.0 * distinct_codes_mapped / nullif(distinct_codes, 0), 2) as distinct_code_coverage_pct,
    case when category = 'cohort code sets' then 100.0 else {{ var('coverage_min_pct') }} end as required_pct
from (select * from by_category union all select * from cohort_codes) as combined
