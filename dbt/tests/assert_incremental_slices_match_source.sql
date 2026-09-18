-- Incremental correctness (Section 9.2.7), run on every build: each layer must hold exactly the content a
-- full recomputation of the selected revision would produce. Every layer is reduced to (count, content
-- digest) per source file with ONE aggregate pass, and the digests are compared:
--
--   raw snapshot  ==  staging slices                     (patient + row fingerprint multiset)
--   staging       ==  intermediate person slices         (patient + row fingerprint multiset)
--   intermediate  ==  star facts                         (source event key multiset)
--   recomputed mapping == int_omop_event_candidates      (source event key + mapping ordinal multiset)
--
-- The digest is an order-independent sum of 60-bit row-hash prefixes, so a missing, duplicated or altered
-- row changes it. Earlier this test used multiset EXCEPTs over 1.34M-row sets and cost 247s of a 272s gate;
-- the aggregate form is equivalent in strength and runs in seconds. Zero rows = pass.
{% set digest %}sum(('x' || substr(md5(key_text), 1, 15))::bit(60)::bigint::numeric){% endset %}

with raw_rows as (
    select 'patients' as source_file, r.id || ':' || r._row_fingerprint as key_text
    from {{ source('raw', 'patients') }} as r
    inner join {{ ref('stg_ops__effective_patient_batch') }} as eff
        on eff.patient_id = r.id and eff.batch_id = r._batch_id
    union all
    select 'encounters', r.patient || ':' || r._row_fingerprint
    from {{ source('raw', 'encounters') }} as r
    inner join {{ ref('stg_ops__effective_patient_batch') }} as eff
        on eff.patient_id = r.patient and eff.batch_id = r._batch_id
    union all
    select 'conditions', r.patient || ':' || r._row_fingerprint
    from {{ source('raw', 'conditions') }} as r
    inner join {{ ref('stg_ops__effective_patient_batch') }} as eff
        on eff.patient_id = r.patient and eff.batch_id = r._batch_id
    union all
    select 'medications', r.patient || ':' || r._row_fingerprint
    from {{ source('raw', 'medications') }} as r
    inner join {{ ref('stg_ops__effective_patient_batch') }} as eff
        on eff.patient_id = r.patient and eff.batch_id = r._batch_id
    union all
    select 'observations', r.patient || ':' || r._row_fingerprint
    from {{ source('raw', 'observations') }} as r
    inner join {{ ref('stg_ops__effective_patient_batch') }} as eff
        on eff.patient_id = r.patient and eff.batch_id = r._batch_id
),

staging_rows as (
    select 'patients' as source_file, patient_id || ':' || source_row_fingerprint as key_text
    from {{ ref('stg_synthea__patients') }}
    union all
    select 'encounters', patient_id || ':' || source_row_fingerprint from {{ ref('stg_synthea__encounters') }}
    union all
    select 'conditions', patient_id || ':' || source_row_fingerprint from {{ ref('stg_synthea__conditions') }}
    union all
    select 'medications', patient_id || ':' || source_row_fingerprint from {{ ref('stg_synthea__medications') }}
    union all
    select 'observations', patient_id || ':' || source_row_fingerprint from {{ ref('stg_synthea__observations') }}
),

-- Intermediate slices hold only events whose patient exists; orphans are compared separately below.
intermediate_rows as (
    select 'encounters' as source_file, patient_id || ':' || source_row_fingerprint as key_text
    from {{ ref('int_encounters') }}
    union all
    select 'conditions', patient_id || ':' || source_row_fingerprint from {{ ref('int_conditions') }}
    union all
    select 'medications', patient_id || ':' || source_row_fingerprint from {{ ref('int_medications') }}
    union all
    select 'observations', patient_id || ':' || source_row_fingerprint from {{ ref('int_observations') }}
),

staging_with_patient as (
    select 'encounters' as source_file, e.patient_id || ':' || e.source_row_fingerprint as key_text
    from {{ ref('stg_synthea__encounters') }} as e
    inner join {{ ref('stg_synthea__patients') }} as p on p.patient_id = e.patient_id
    union all
    select 'conditions', c.patient_id || ':' || c.source_row_fingerprint
    from {{ ref('stg_synthea__conditions') }} as c
    inner join {{ ref('stg_synthea__patients') }} as p on p.patient_id = c.patient_id
    union all
    select 'medications', m.patient_id || ':' || m.source_row_fingerprint
    from {{ ref('stg_synthea__medications') }} as m
    inner join {{ ref('stg_synthea__patients') }} as p on p.patient_id = m.patient_id
    union all
    select 'observations', o.patient_id || ':' || o.source_row_fingerprint
    from {{ ref('stg_synthea__observations') }} as o
    inner join {{ ref('stg_synthea__patients') }} as p on p.patient_id = o.patient_id
),

star_rows as (
    select 'encounters' as source_file, source_event_key as key_text from {{ ref('fct_encounter') }}
    union all select 'conditions', source_event_key from {{ ref('fct_condition') }}
    union all select 'medications', source_event_key from {{ ref('fct_medication') }}
    union all select 'observations', source_event_key from {{ ref('fct_observation') }}
),

intermediate_event_keys as (
    select 'encounters' as source_file, source_row_fingerprint as key_text from {{ ref('int_encounters') }}
    union all select 'conditions', source_event_key from {{ ref('int_conditions') }}
    union all select 'medications', source_event_key from {{ ref('int_medications') }}
    union all select 'observations', source_event_key from {{ ref('int_observations') }}
),

candidates_stored as (
    select source_file, source_event_key || '#' || mapping_ordinal as key_text
    from {{ ref('int_omop_event_candidates') }}
),

candidates_recomputed as (
    select e.source_file, e.source_event_key || '#' || coalesce(m.mapping_ordinal, 1)::text as key_text
    from {{ ref('int_clinical_events') }} as e
    left join {{ ref('int_concept_map') }} as m
        on m.source_vocabulary_id = e.source_vocabulary_id and m.source_code = e.source_code
    where e.patient_exists
),

digests as (
    select 'raw' as layer, source_file, count(*) as row_count, {{ digest }} as digest from raw_rows group by 2
    union all
    select 'staging', source_file, count(*), {{ digest }} from staging_rows group by 2
    union all
    select 'staging_with_patient', source_file, count(*), {{ digest }} from staging_with_patient group by 2
    union all
    select 'intermediate', source_file, count(*), {{ digest }} from intermediate_rows group by 2
    union all
    select 'intermediate_keys', source_file, count(*), {{ digest }} from intermediate_event_keys group by 2
    union all
    select 'star', source_file, count(*), {{ digest }} from star_rows group by 2
    union all
    select 'candidates_stored', source_file, count(*), {{ digest }} from candidates_stored group by 2
    union all
    select 'candidates_recomputed', source_file, count(*), {{ digest }} from candidates_recomputed group by 2
),

comparisons as (
    select 'raw_vs_staging' as comparison, 'raw' as left_layer, 'staging' as right_layer
    union all select 'staging_vs_intermediate', 'staging_with_patient', 'intermediate'
    union all select 'intermediate_vs_star', 'intermediate_keys', 'star'
    union all select 'candidates_vs_recomputed', 'candidates_stored', 'candidates_recomputed'
),

files as (
    select distinct source_file from digests
)

select
    c.comparison,
    f.source_file,
    l.row_count as left_rows,
    r.row_count as right_rows,
    l.digest as left_digest,
    r.digest as right_digest
from comparisons as c
cross join files as f
left join digests as l on l.layer = c.left_layer and l.source_file = f.source_file
left join digests as r on r.layer = c.right_layer and r.source_file = f.source_file
where coalesce(l.row_count, -1) <> coalesce(r.row_count, -1)
   or coalesce(l.digest, -1) <> coalesce(r.digest, -1)
