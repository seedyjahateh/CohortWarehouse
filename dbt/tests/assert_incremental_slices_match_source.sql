-- Incremental correctness (Section 9.2.7, run every build): the person-slice tables must hold exactly the
-- content a full recomputation from the selected revision would produce. Compares event identity sets
-- (source_event_key per person) between incremental tables and the non-incremental event views, and
-- between intermediate tables, star facts and OMOP crosswalk. Zero rows = pass.
-- Staging is itself a change-candidate slice, so it is compared against the raw snapshot directly (by
-- multiset counts per person and content fingerprint), not just against the models built from it.
with raw_counts as (
    select 'patients' as f, r.id as patient_id, r._row_fingerprint as fp, count(*) as n
    from {{ source('raw', 'patients') }} as r
    inner join {{ ref('stg_ops__effective_patient_batch') }} as eff
        on eff.patient_id = r.id and eff.batch_id = r._batch_id
    group by 1, 2, 3
    union all
    select 'encounters', r.patient, r._row_fingerprint, count(*)
    from {{ source('raw', 'encounters') }} as r
    inner join {{ ref('stg_ops__effective_patient_batch') }} as eff
        on eff.patient_id = r.patient and eff.batch_id = r._batch_id
    group by 1, 2, 3
    union all
    select 'conditions', r.patient, r._row_fingerprint, count(*)
    from {{ source('raw', 'conditions') }} as r
    inner join {{ ref('stg_ops__effective_patient_batch') }} as eff
        on eff.patient_id = r.patient and eff.batch_id = r._batch_id
    group by 1, 2, 3
    union all
    select 'medications', r.patient, r._row_fingerprint, count(*)
    from {{ source('raw', 'medications') }} as r
    inner join {{ ref('stg_ops__effective_patient_batch') }} as eff
        on eff.patient_id = r.patient and eff.batch_id = r._batch_id
    group by 1, 2, 3
    union all
    select 'observations', r.patient, r._row_fingerprint, count(*)
    from {{ source('raw', 'observations') }} as r
    inner join {{ ref('stg_ops__effective_patient_batch') }} as eff
        on eff.patient_id = r.patient and eff.batch_id = r._batch_id
    group by 1, 2, 3
),

staging_counts as (
    select 'patients' as f, patient_id, source_row_fingerprint as fp, count(*) as n
    from {{ ref('stg_synthea__patients') }} group by 1, 2, 3
    union all
    select 'encounters', patient_id, source_row_fingerprint, count(*)
    from {{ ref('stg_synthea__encounters') }} group by 1, 2, 3
    union all
    select 'conditions', patient_id, source_row_fingerprint, count(*)
    from {{ ref('stg_synthea__conditions') }} group by 1, 2, 3
    union all
    select 'medications', patient_id, source_row_fingerprint, count(*)
    from {{ ref('stg_synthea__medications') }} group by 1, 2, 3
    union all
    select 'observations', patient_id, source_row_fingerprint, count(*)
    from {{ ref('stg_synthea__observations') }} group by 1, 2, 3
),

expected as (
    select 'conditions' as f, patient_id, source_event_key from {{ ref('int_condition_events') }} where patient_exists
    union all
    select 'medications', patient_id, source_event_key from {{ ref('int_medication_events') }} where patient_exists
    union all
    select 'observations', patient_id, source_event_key from {{ ref('int_observation_events') }} where patient_exists
    union all
    select 'encounters', e.patient_id, e.source_row_fingerprint
    from {{ ref('stg_synthea__encounters') }} as e
    inner join {{ ref('stg_synthea__patients') }} as p on p.patient_id = e.patient_id
),

intermediate as (
    select 'conditions' as f, patient_id, source_event_key from {{ ref('int_conditions') }}
    union all select 'medications', patient_id, source_event_key from {{ ref('int_medications') }}
    union all select 'observations', patient_id, source_event_key from {{ ref('int_observations') }}
    union all select 'encounters', patient_id, source_row_fingerprint from {{ ref('int_encounters') }}
),

star as (
    select 'conditions' as f, p.patient_id, c.source_event_key
    from {{ ref('fct_condition') }} as c join {{ ref('int_patients') }} as p on p.patient_key = c.patient_key
    union all
    select 'medications', p.patient_id, m.source_event_key
    from {{ ref('fct_medication') }} as m join {{ ref('int_patients') }} as p on p.patient_key = m.patient_key
    union all
    select 'observations', p.patient_id, o.source_event_key
    from {{ ref('fct_observation') }} as o join {{ ref('int_patients') }} as p on p.patient_key = o.patient_key
    union all
    select 'encounters', p.patient_id, e.source_event_key
    from {{ ref('fct_encounter') }} as e join {{ ref('int_patients') }} as p on p.patient_key = e.patient_key
),

candidates_expected as (
    select patient_id, source_event_key, mapping_ordinal
    from {{ ref('int_omop_event_candidates') }}
),

candidates_recomputed as (
    select e.patient_id, e.source_event_key, coalesce(m.mapping_ordinal, 1) as mapping_ordinal
    from {{ ref('int_clinical_events') }} as e
    left join {{ ref('int_concept_map') }} as m
        on m.source_vocabulary_id = e.source_vocabulary_id and m.source_code = e.source_code
    where e.patient_exists
)

(select 'staging_missing_vs_raw' as problem, f, patient_id, fp || '#' || n from raw_counts
 except select 'staging_missing_vs_raw', f, patient_id, fp || '#' || n from staging_counts)
union all
(select 'staging_stale_vs_raw', f, patient_id, fp || '#' || n from staging_counts
 except select 'staging_stale_vs_raw', f, patient_id, fp || '#' || n from raw_counts)
union all
(select 'intermediate_missing' as problem, * from expected except select 'intermediate_missing', * from intermediate)
union all
(select 'intermediate_stale', * from intermediate except select 'intermediate_stale', * from expected)
union all
(select 'star_missing', * from intermediate except select 'star_missing', * from star)
union all
(select 'star_stale', * from star except select 'star_stale', * from intermediate)
union all
(select 'candidate_missing', 'omop', patient_id, source_event_key || '#' || mapping_ordinal from candidates_recomputed
 except select 'candidate_missing', 'omop', patient_id, source_event_key || '#' || mapping_ordinal from candidates_expected)
union all
(select 'candidate_stale', 'omop', patient_id, source_event_key || '#' || mapping_ordinal from candidates_expected
 except select 'candidate_stale', 'omop', patient_id, source_event_key || '#' || mapping_ordinal from candidates_recomputed)
