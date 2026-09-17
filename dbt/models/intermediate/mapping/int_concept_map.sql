{{ config(materialized='table', indexes=[{'columns': ['source_vocabulary_id', 'source_code']}]) }}
-- Grain: one (source vocabulary, source code, mapping ordinal). Unmapped codes have one row with
-- target_concept_id 0. Implements MAP-02: a valid standard source concept is used directly;
-- otherwise follow VALID 'Maps to' relationships to VALID standard targets. Text is matched by code
-- within a vocabulary, never by display name.
-- Codes are read straight from staging (no occurrence-ordinal windows needed for a distinct code list).
with codes as (
    select distinct alias.omop_vocabulary_id as source_vocabulary_id, c.source_code
    from {{ ref('stg_synthea__conditions') }} as c
    inner join {{ ref('source_vocabulary_aliases') }} as alias
        on alias.source_file = 'conditions'
       and alias.source_system = coalesce(nullif(c.source_system, ''), '(default)')
    union
    select distinct alias.omop_vocabulary_id, m.source_code
    from {{ ref('stg_synthea__medications') }} as m
    inner join {{ ref('source_vocabulary_aliases') }} as alias
        on alias.source_file = 'medications' and alias.source_system = '(default)'
    union
    select distinct alias.omop_vocabulary_id, o.source_code
    from {{ ref('stg_synthea__observations') }} as o
    inner join {{ ref('source_vocabulary_aliases') }} as alias
        on alias.source_file = 'observations' and alias.source_system = '(default)'
),

source_concepts as (
    select
        c.source_vocabulary_id,
        c.source_code,
        sc.concept_id as source_concept_id,
        sc.concept_name as source_concept_name,
        coalesce(sc.standard_concept = 'S' and sc.invalid_reason is null, false) as source_is_valid_standard
    from codes as c
    left join {{ source('vocab', 'concept') }} as sc
        on sc.vocabulary_id = c.source_vocabulary_id
       and sc.concept_code = c.source_code
),

targets as (
    select source_vocabulary_id, source_code, source_concept_id as target_concept_id,
           'standard_source' as mapping_path
    from source_concepts
    where source_is_valid_standard

    union

    select s.source_vocabulary_id, s.source_code, t.concept_id, 'maps_to'
    from source_concepts as s
    inner join {{ source('vocab', 'concept_relationship') }} as cr
        on cr.concept_id_1 = s.source_concept_id
       and cr.relationship_id = 'Maps to'
       and cr.invalid_reason is null
    inner join {{ source('vocab', 'concept') }} as t
        on t.concept_id = cr.concept_id_2
       and t.standard_concept = 'S'
       and t.invalid_reason is null
    where s.source_concept_id is not null
      and not s.source_is_valid_standard
),

value_maps as (
    select
        s.source_vocabulary_id,
        s.source_code,
        min(t.concept_id) as value_as_concept_id,
        count(distinct t.concept_id) as value_map_count
    from source_concepts as s
    inner join {{ source('vocab', 'concept_relationship') }} as cr
        on cr.concept_id_1 = s.source_concept_id
       and cr.relationship_id = 'Maps to value'
       and cr.invalid_reason is null
    inner join {{ source('vocab', 'concept') }} as t
        on t.concept_id = cr.concept_id_2
       and t.invalid_reason is null
    group by s.source_vocabulary_id, s.source_code
),

ranked as (
    select
        *,
        row_number() over (partition by source_vocabulary_id, source_code order by target_concept_id)
            as mapping_ordinal,
        count(*) over (partition by source_vocabulary_id, source_code) as target_count
    from targets
)

select
    s.source_vocabulary_id,
    s.source_code,
    coalesce(s.source_concept_id, 0) as source_concept_id,
    s.source_concept_name,
    coalesce(r.mapping_ordinal, 1)::integer as mapping_ordinal,
    coalesce(r.target_concept_id, 0) as target_concept_id,
    tc.domain_id as target_domain_id,
    tc.concept_name as target_concept_name,
    coalesce(r.target_count, 0)::integer as target_count,
    v.value_as_concept_id,
    coalesce(v.value_map_count, 0)::integer as value_map_count,
    case
        when s.source_concept_id is null then 'source_concept_not_found'
        when r.target_concept_id is null then 'no_valid_standard_target'
        else r.mapping_path
    end as mapping_status
from source_concepts as s
left join ranked as r
    on r.source_vocabulary_id = s.source_vocabulary_id and r.source_code = s.source_code
left join {{ source('vocab', 'concept') }} as tc
    on tc.concept_id = r.target_concept_id
left join value_maps as v
    on v.source_vocabulary_id = s.source_vocabulary_id and v.source_code = s.source_code
