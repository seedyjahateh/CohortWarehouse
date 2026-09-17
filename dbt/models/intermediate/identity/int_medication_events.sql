{{ config(materialized='view') }}
-- Grain: one source medication record, identity = row fingerprint + occurrence ordinal.
select
    m.*,
    m.source_row_fingerprint || ':' || row_number() over (
        partition by m.dataset_id, m.patient_id, m.source_row_fingerprint
        order by m.source_batch_id, m.source_record_number
    ) as source_event_key,
    alias.omop_vocabulary_id as source_vocabulary_id,
    coalesce(alias.is_assumed_default, false) as vocabulary_assumed,
    coalesce(alias.omop_vocabulary_id, 'UNRESOLVED:(none)') || '|' || m.source_code as clinical_code_natural_key,
    p.patient_id is not null as patient_exists
from {{ ref('stg_synthea__medications') }} as m
left join {{ ref('source_vocabulary_aliases') }} as alias
    on alias.source_file = 'medications' and alias.source_system = '(default)'
left join {{ ref('stg_synthea__patients') }} as p
    on p.dataset_id = m.dataset_id and p.patient_id = m.patient_id
