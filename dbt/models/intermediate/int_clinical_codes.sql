-- depends_on: {{ ref('int_key_registry') }}
-- Grain: one source code (vocabulary + code) used by a valid clinical event in the selected revision.
with codes as (
    select dataset_id, clinical_code_natural_key, 'conditions' as source_file, source_system,
           source_vocabulary_id, vocabulary_assumed, source_code, source_description
    from {{ ref('int_conditions') }}
    union all
    select dataset_id, clinical_code_natural_key, 'medications', source_system,
           source_vocabulary_id, vocabulary_assumed, source_code, source_description
    from {{ ref('int_medications') }}
    union all
    select dataset_id, clinical_code_natural_key, 'observations', source_system,
           source_vocabulary_id, vocabulary_assumed, source_code, source_description
    from {{ ref('int_observations') }}
),

grouped as (
    select
        dataset_id,
        clinical_code_natural_key,
        min(source_vocabulary_id) as source_vocabulary_id,
        min(source_code) as source_code,
        min(source_description) as source_description,
        string_agg(distinct source_file, ',' order by source_file) as source_files,
        bool_or(vocabulary_assumed) as vocabulary_assumed,
        count(*) as event_count
    from codes
    group by dataset_id, clinical_code_natural_key
),

mapping as (
    select
        source_vocabulary_id,
        source_code,
        min(mapping_status) as mapping_status,
        max(source_concept_id) as source_concept_id,
        max(target_count) as target_count,
        string_agg(target_concept_id::text, ',' order by mapping_ordinal) as target_concept_ids,
        string_agg(target_concept_name, ' | ' order by mapping_ordinal) as target_concept_names,
        string_agg(distinct target_domain_id, ',') as target_domains
    from {{ ref('int_concept_map') }}
    group by source_vocabulary_id, source_code
)

select
    k.surrogate_id as clinical_code_key,
    g.*,
    coalesce(m.mapping_status, 'unresolved_vocabulary') as mapping_status,
    coalesce(m.source_concept_id, 0) as source_concept_id,
    coalesce(m.target_count, 0) as target_count,
    coalesce(m.target_concept_ids, '0') as target_concept_ids,
    m.target_concept_names,
    m.target_domains
from grouped as g
left join mapping as m
    on m.source_vocabulary_id = g.source_vocabulary_id and m.source_code = g.source_code
{{ key_lookup('clinical_code', 'k', 'g.dataset_id', 'g.clinical_code_natural_key') }}
