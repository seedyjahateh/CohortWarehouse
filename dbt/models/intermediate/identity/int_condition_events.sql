{{ config(materialized='view') }}
-- Grain: one source condition record. Identity = row fingerprint + occurrence ordinal (Section 8.4.3):
-- identical rows keep their multiplicity instead of being collapsed.
select
    c.*,
    c.source_row_fingerprint || ':' || c.occurrence_ordinal as source_event_key,
    alias.omop_vocabulary_id as source_vocabulary_id,
    coalesce(alias.is_assumed_default, false) as vocabulary_assumed,
    coalesce(alias.omop_vocabulary_id, 'UNRESOLVED:' || coalesce(c.source_system, '(none)'))
        || '|' || c.source_code as clinical_code_natural_key,
    p.patient_id is not null as patient_exists
from {{ ref('stg_synthea__conditions') }} as c
left join {{ ref('source_vocabulary_aliases') }} as alias
    on alias.source_file = 'conditions'
   and alias.source_system = coalesce(nullif(c.source_system, ''), '(default)')
left join {{ ref('stg_synthea__patients') }} as p
    on p.dataset_id = c.dataset_id and p.patient_id = c.patient_id
