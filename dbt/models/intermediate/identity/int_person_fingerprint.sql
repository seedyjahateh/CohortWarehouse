{{ config(materialized='table', indexes=[{'columns': ['patient_id'], 'unique': True}]) }}
-- Grain: one change candidate (see stg_ops__change_candidate; every referenced patient when narrowing is
-- not provably safe). Fingerprint of the person's clinical row multiset plus patient attributes
-- (Section 9.2, step 2). People outside the delivered scope cannot have changed, so they are not re-hashed.
with candidates as (
    select patient_id from {{ ref('stg_ops__change_candidate') }}
),

person_rows as (
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
    r.dataset_id,
    r.patient_id,
    encode(
        sha256(convert_to(
            string_agg(r.source_file || ':' || r.source_row_fingerprint, ','
                       order by r.source_file, r.source_row_fingerprint),
            'UTF8'
        )),
        'hex'
    ) as person_fingerprint,
    count(*) as source_row_count
from person_rows as r
inner join candidates as c on c.patient_id = r.patient_id
group by r.dataset_id, r.patient_id
