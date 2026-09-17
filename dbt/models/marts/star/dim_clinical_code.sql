-- Grain: one source vocabulary + code used by a valid clinical event. Type 1; mapping status reflects
-- the pinned vocabulary version recorded in bi_release_status / ops.pipeline_run.
select
    clinical_code_key,
    source_vocabulary_id,
    source_code,
    source_description,
    source_files,
    vocabulary_assumed,
    mapping_status,
    source_concept_id,
    target_count as mapped_target_count,
    target_concept_ids as mapped_concept_ids,
    target_concept_names as mapped_concept_names,
    target_domains as mapped_domains,
    mapping_status in ('standard_source', 'maps_to') as is_mapped
from {{ ref('int_clinical_codes') }}
