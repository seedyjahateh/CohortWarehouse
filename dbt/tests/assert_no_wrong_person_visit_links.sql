-- STG-03 (blocking): a supplied encounter reference that belongs to ANOTHER person. Computed directly from
-- the selected revision (not from incremental tables) so a change to either person is always caught.
with events as (
    select 'conditions' as source_file, patient_id, encounter_id, source_batch_id, source_record_number
    from {{ ref('stg_synthea__conditions') }}
    union all
    select 'medications', patient_id, encounter_id, source_batch_id, source_record_number
    from {{ ref('stg_synthea__medications') }}
    union all
    select 'observations', patient_id, encounter_id, source_batch_id, source_record_number
    from {{ ref('stg_synthea__observations') }}
)

select ev.source_file, ev.source_batch_id, ev.source_record_number
from events as ev
inner join {{ ref('stg_synthea__encounters') }} as enc
    on enc.encounter_id = ev.encounter_id
where ev.encounter_id is not null
  and enc.patient_id <> ev.patient_id
