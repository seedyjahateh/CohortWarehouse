-- OMOP reconciliation (Section 11.3): C1-C3 recomputed from the OMOP mart alone, using the SAME explicit
-- source-code-set scope through preserved source values + source concept vocabulary + a valid mapped
-- target (never descendant expansion), must equal bi_cohort_membership exactly.
with rev as (
    select as_of_date as d from {{ ref('stg_ops__selected_revision') }}
),

people as (
    select
        p.person_id,
        make_date(p.year_of_birth, p.month_of_birth, p.day_of_birth) as birth_date,
        dth.death_date
    from {{ ref('omop_person') }} as p
    left join {{ ref('omop_death') }} as dth on dth.person_id = p.person_id
),

eligible as (
    select pe.person_id
    from people as pe, rev
    where extract(year from age(rev.d, pe.birth_date)) >= 18
      and (pe.death_date is null or pe.death_date > rev.d)
      and exists (
          select 1 from {{ ref('omop_visit_occurrence') }} as v
          where v.person_id = pe.person_id and v.visit_start_date between rev.d - 364 and rev.d
      )
),

condition_like as (
    -- Hypertension codes map to the Condition domain; the SNOMED source-concept join below keeps the
    -- comparison inside the explicit source-code-set scope.
    select person_id, condition_source_value as source_value, condition_source_concept_id as source_concept_id,
           condition_concept_id as target_concept_id, condition_start_date as start_date,
           condition_end_date as end_date
    from {{ ref('omop_condition_occurrence') }}
),

c1 as (
    select distinct c.person_id
    from condition_like as c
    inner join {{ source('vocab', 'concept') }} as sc
        on sc.concept_id = c.source_concept_id and sc.vocabulary_id = 'SNOMED'
    cross join rev
    where c.source_value in (
              select source_code from {{ ref('cohort_code_sets') }} where code_set_id = 'HTN_CONDITIONS'
          )
      and c.target_concept_id <> 0
      and c.start_date <= rev.d
      and (c.end_date is null or c.end_date >= rev.d)
      and c.person_id in (select person_id from eligible)
),

systolic as (
    select
        m.person_id,
        m.value_as_number,
        row_number() over (
            partition by m.person_id
            order by coalesce(m.measurement_datetime, m.measurement_date::timestamp) desc, x.source_event_key desc
        ) as recency
    from {{ ref('omop_measurement') }} as m
    inner join {{ ref('cw_event_crosswalk') }} as x
        on x.destination_table = 'measurement' and x.omop_row_id = m.measurement_id
    inner join {{ source('vocab', 'concept') }} as sc
        on sc.concept_id = m.measurement_source_concept_id and sc.vocabulary_id = 'LOINC'
    cross join rev
    where m.measurement_source_value in (
              select source_code from {{ ref('cohort_code_sets') }} where code_set_id = 'SYSTOLIC_BP'
          )
      and m.measurement_concept_id <> 0
      and m.measurement_date between rev.d - 89 and rev.d
      and m.value_as_number is not null
      and m.unit_source_value in (select source_unit from {{ ref('unit_policy') }} where approved_for_systolic)
),

c2 as (
    select person_id from systolic
    where recency = 1
      and value_as_number > (select systolic_threshold_exclusive from {{ ref('cohort_definitions') }} where cohort_id = 'C2')
      and person_id in (select person_id from c1)
),

c3 as (
    select v.person_id
    from {{ ref('omop_visit_occurrence') }} as v, rev
    where v.visit_start_date between rev.d - 364 and rev.d
      and v.person_id in (select person_id from eligible)
    group by v.person_id
    having count(distinct v.visit_occurrence_id) >= 3
),

omop_based as (
    select 'C1' as cohort_id, person_id as patient_key from c1
    union all select 'C2', person_id from c2
    union all select 'C3', person_id from c3
),

modelled as (
    select cohort_id, patient_key from {{ ref('bi_cohort_membership') }}
)

(select 'missing_from_bi' as difference, * from omop_based except select 'missing_from_bi', * from modelled)
union all
(select 'missing_from_omop', * from modelled except select 'missing_from_omop', * from omop_based)
