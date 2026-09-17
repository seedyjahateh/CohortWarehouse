-- Cohort correctness (G-02, Section 11.1): an INDEPENDENT implementation of C1-C3 written directly against
-- typed staging views and seeds, without any intermediate or BI model logic, must produce exactly the same
-- (cohort, patient) set as bi_cohort_membership. Returns the symmetric difference (zero rows = pass).
-- Formulations deliberately differ from the models (e.g. age via month/day comparison, not age()).
with rev as (
    select as_of_date as d from {{ ref('stg_ops__selected_revision') }}
),

patients as (
    select patient_id, birth_date, death_date from {{ ref('stg_synthea__patients') }}
),

encounters as (
    select e.patient_id, e.encounter_id, (e.start_at at time zone 'UTC')::date as start_day
    from {{ ref('stg_synthea__encounters') }} as e
    where exists (select 1 from patients as p where p.patient_id = e.patient_id)
),

eligible as (
    select p.patient_id
    from patients as p, rev
    where (
            extract(year from rev.d) - extract(year from p.birth_date) > 18
            or (
                extract(year from rev.d) - extract(year from p.birth_date) = 18
                and (extract(month from rev.d), extract(day from rev.d))
                    >= (extract(month from p.birth_date), extract(day from p.birth_date))
            )
          )
      and (p.death_date is null or p.death_date > rev.d)
      and exists (
          select 1 from encounters as e
          where e.patient_id = p.patient_id and e.start_day >= rev.d - 364 and e.start_day <= rev.d
      )
),

htn_codes as (
    select source_code from {{ ref('cohort_code_sets') }}
    where code_set_id = 'HTN_CONDITIONS' and omop_vocabulary_id = 'SNOMED'
),

snomed_systems as (
    select source_system from {{ ref('source_vocabulary_aliases') }}
    where source_file = 'conditions' and omop_vocabulary_id = 'SNOMED'
),

c1 as (
    select distinct c.patient_id
    from {{ ref('stg_synthea__conditions') }} as c, rev
    where c.source_code in (select source_code from htn_codes)
      and coalesce(nullif(c.source_system, ''), '(default)') in (select source_system from snomed_systems)
      and c.start_date <= rev.d
      and (c.stop_date is null or c.stop_date >= rev.d)
      and c.patient_id in (select patient_id from eligible)
),

systolic as (
    select
        o.patient_id,
        o.value_text,
        row_number() over (
            partition by o.patient_id
            order by o.observed_at desc, o.source_row_fingerprint desc
        ) as recency
    from {{ ref('stg_synthea__observations') }} as o, rev
    where o.source_code in (select source_code from {{ ref('cohort_code_sets') }} where code_set_id = 'SYSTOLIC_BP')
      and (o.observed_at at time zone 'UTC')::date between rev.d - 89 and rev.d
      and o.source_value_type = 'numeric'
      and o.value_text ~ '^\s*[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)\s*$'
      and o.source_unit in (select source_unit from {{ ref('unit_policy') }} where approved_for_systolic)
),

c2 as (
    select s.patient_id
    from systolic as s
    where s.recency = 1
      and s.value_text::numeric > (select systolic_threshold_exclusive from {{ ref('cohort_definitions') }} where cohort_id = 'C2')
      and s.patient_id in (select patient_id from c1)
),

c3 as (
    select e.patient_id
    from encounters as e, rev
    where e.start_day between rev.d - 364 and rev.d
      and e.patient_id in (select patient_id from eligible)
    group by e.patient_id
    having count(distinct e.encounter_id) >= (select min_encounters from {{ ref('cohort_definitions') }} where cohort_id = 'C3')
),

independent as (
    select 'C1' as cohort_id, patient_id from c1
    union all select 'C2', patient_id from c2
    union all select 'C3', patient_id from c3
),

modelled as (
    select m.cohort_id, p.patient_id
    from {{ ref('bi_cohort_membership') }} as m
    inner join {{ ref('int_patients') }} as p on p.patient_key = m.patient_key
)

(select 'missing_from_model' as difference, * from independent except select 'missing_from_model', * from modelled)
union all
(select 'unexpected_in_model', * from modelled except select 'unexpected_in_model', * from independent)
