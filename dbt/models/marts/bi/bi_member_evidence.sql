-- Grain: one (cohort, member, evidence event). Drill-through for US-05: pseudonymous key, evidence dates,
-- source code, mapped concept where available and the rule applied. No names, addresses or source ids.
with rev as (
    select as_of_date from {{ ref('stg_ops__selected_revision') }}
),

mapped as (
    select source_vocabulary_id, source_code,
           string_agg(target_concept_id::text, ',' order by mapping_ordinal) as mapped_concept_ids,
           string_agg(target_concept_name, ' | ' order by mapping_ordinal) as mapped_concept_names
    from {{ ref('int_concept_map') }}
    where target_concept_id <> 0
    group by source_vocabulary_id, source_code
),

members as (
    select m.*, s.patient_pseudo_id
    from {{ ref('bi_cohort_membership') }} as m
    inner join {{ ref('bi_patient_snapshot') }} as s on s.patient_key = m.patient_key
)

-- Qualifying conditions (every qualifying occurrence, flagging the one cited in membership)
select
    m.cohort_id, m.patient_key, m.patient_pseudo_id,
    'qualifying condition' as evidence_type,
    c.event_key as evidence_key,
    c.start_date as evidence_date,
    c.stop_date as evidence_end_date,
    c.source_vocabulary_id, c.source_code, c.source_description,
    mp.mapped_concept_ids, mp.mapped_concept_names,
    null::numeric as value_as_number, null::text as unit,
    c.event_key = m.qualifying_condition_key as is_cited_in_membership
from members as m
inner join {{ ref('cohort_definitions') }} as d on d.cohort_id = m.cohort_id
inner join {{ ref('cohort_code_sets') }} as cs on cs.code_set_id = d.condition_code_set_id
inner join {{ ref('int_conditions') }} as c
    on c.patient_key = m.patient_key and c.source_vocabulary_id = cs.omop_vocabulary_id and c.source_code = cs.source_code
cross join rev
left join mapped as mp on mp.source_vocabulary_id = c.source_vocabulary_id and mp.source_code = c.source_code
where c.start_date <= rev.as_of_date and (c.stop_date is null or c.stop_date >= rev.as_of_date)

union all

-- Latest valid systolic measurement (C2)
select
    m.cohort_id, m.patient_key, m.patient_pseudo_id,
    'latest valid systolic', o.event_key, o.observation_date, null::date,
    o.source_vocabulary_id, o.source_code, o.source_description,
    mp.mapped_concept_ids, mp.mapped_concept_names,
    o.value_as_number, o.source_unit, true
from members as m
inner join {{ ref('int_observations') }} as o on o.event_key = m.qualifying_measurement_key
left join mapped as mp on mp.source_vocabulary_id = o.source_vocabulary_id and mp.source_code = o.source_code

union all

-- Encounters in the lookback window (C3)
select
    m.cohort_id, m.patient_key, m.patient_pseudo_id,
    'encounter in window', e.encounter_key, e.start_date, e.stop_date,
    null, e.encounter_class, e.encounter_description,
    null, null, null::numeric, null, true
from members as m
inner join {{ ref('int_encounters') }} as e on e.patient_key = m.patient_key
cross join rev
where m.cohort_id = 'C3' and e.start_date between rev.as_of_date - 364 and rev.as_of_date
