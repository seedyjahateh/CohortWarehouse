{{ config(alias='cdm_source') }}
-- Grain: exactly one row describing source provenance, ETL version, CDM version and vocabulary version.
select
    'CohortWarehouse synthetic Synthea mart'::varchar(255) as cdm_source_name,
    ('CW_' || upper(rev.dataset_id))::varchar(25) as cdm_source_abbreviation,
    'CohortWarehouse demonstration project (synthetic data only)'::varchar(255) as cdm_holder,
    ('SYNTHETIC DATA - DEMONSTRATION ONLY. Scoped OMOP CDM 5.4 mart built from generator-produced '
     || 'Synthea CSV exports (batch ' || rev.target_batch_id || ', revision ' || rev.target_revision
     || ', as-of ' || rev.as_of_date || '). Populated tables and limitations: docs/omop-scope.md.')::text
        as source_description,
    'https://github.com/synthetichealth/synthea/wiki/CSV-File-Data-Dictionary'::varchar(255)
        as source_documentation_reference,
    ('cohortwarehouse@' || '{{ git_sha() }}')::varchar(255) as cdm_etl_reference,
    rev.target_delivered_at::date as source_release_date,
    current_date as cdm_release_date,
    '5.4'::varchar(10) as cdm_version,
    {{ fixed_concept('cdm_version') }}::integer as cdm_version_concept_id,
    left(coalesce(voc.vocabulary_version, 'unknown'), 20)::varchar(20) as vocabulary_version
from {{ ref('stg_ops__selected_revision') }} as rev
left join {{ source('vocab', 'vocabulary') }} as voc
    on voc.vocabulary_id = 'None'
