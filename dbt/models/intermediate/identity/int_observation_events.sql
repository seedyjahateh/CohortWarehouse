{{ config(materialized='view') }}
-- Grain: one source observation record (repeated same-time values preserved),
-- identity = row fingerprint + occurrence ordinal.
select
    o.*,
    o.source_row_fingerprint || ':' || o.occurrence_ordinal as source_event_key,
    alias.omop_vocabulary_id as source_vocabulary_id,
    coalesce(alias.is_assumed_default, false) as vocabulary_assumed,
    coalesce(alias.omop_vocabulary_id, 'UNRESOLVED:(none)') || '|' || o.source_code as clinical_code_natural_key,
    unit.canonical_unit,
    coalesce(unit.approved_for_systolic, false) as unit_approved_for_systolic,
    p.patient_id is not null as patient_exists
from {{ ref('stg_synthea__observations') }} as o
left join {{ ref('source_vocabulary_aliases') }} as alias
    on alias.source_file = 'observations' and alias.source_system = '(default)'
left join {{ ref('unit_policy') }} as unit
    on unit.source_unit = o.source_unit
left join {{ ref('stg_synthea__patients') }} as p
    on p.dataset_id = o.dataset_id and p.patient_id = o.patient_id
