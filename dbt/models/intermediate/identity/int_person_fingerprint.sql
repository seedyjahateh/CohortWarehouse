-- Grain: one patient id referenced anywhere in the selected revision (including orphan references).
-- Fingerprint of the person's clinical row multiset plus patient attributes (Section 9.2, step 2).
with person_rows as (
    select dataset_id, patient_id, 'patients' as source_file, source_row_fingerprint
    from {{ ref('stg_synthea__patients') }}
    union all
    select dataset_id, patient_id, 'encounters', source_row_fingerprint
    from {{ ref('stg_synthea__encounters') }}
    union all
    select dataset_id, patient_id, 'conditions', source_row_fingerprint
    from {{ ref('stg_synthea__conditions') }}
    union all
    select dataset_id, patient_id, 'medications', source_row_fingerprint
    from {{ ref('stg_synthea__medications') }}
    union all
    select dataset_id, patient_id, 'observations', source_row_fingerprint
    from {{ ref('stg_synthea__observations') }}
)

select
    dataset_id,
    patient_id,
    encode(
        sha256(convert_to(
            string_agg(source_file || ':' || source_row_fingerprint, ',' order by source_file, source_row_fingerprint),
            'UTF8'
        )),
        'hex'
    ) as person_fingerprint,
    count(*) as source_row_count
from person_rows
group by dataset_id, patient_id
