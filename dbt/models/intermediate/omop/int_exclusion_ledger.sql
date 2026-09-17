-- Grain: one (source record or person, exclusion reason). STG-05: no unexplained record loss.
-- `event_retained` distinguishes informational entries (e.g. a nulled visit link) from true exclusions.
-- Contains no raw identifiers: events use their content key, people their pseudonymous id.
with rev as (
    select as_of_date from {{ ref('stg_ops__selected_revision') }}
)

-- Orphan events: patient reference does not exist. Never assigned an Unknown patient.
-- (Content fingerprint is the key: orphans never receive registry keys.)
select 'orphan_patient' as exclusion_category, 'patient reference not found' as reason,
       orphan.source_file, orphan.source_file || '-row:' || orphan.source_row_fingerprint as source_key,
       null::text as patient_pseudo_id, 'star,omop' as affected_marts,
       false as event_retained, false as is_blocking, orphan.source_batch_id, orphan.source_record_number
from (
    select 'conditions' as source_file, dataset_id, patient_id, source_row_fingerprint, source_batch_id,
           source_record_number
    from {{ ref('stg_synthea__conditions') }}
    union all
    select 'medications', dataset_id, patient_id, source_row_fingerprint, source_batch_id, source_record_number
    from {{ ref('stg_synthea__medications') }}
    union all
    select 'observations', dataset_id, patient_id, source_row_fingerprint, source_batch_id, source_record_number
    from {{ ref('stg_synthea__observations') }}
) as orphan
left join {{ ref('int_patients') }} as p
    on p.dataset_id = orphan.dataset_id and p.patient_id = orphan.patient_id
where p.patient_id is null

union all

select 'orphan_patient', 'patient reference not found', 'encounters', 'encounter-row:' || e.source_row_fingerprint,
       null, 'star,omop', false, false, e.source_batch_id, e.source_record_number
from {{ ref('stg_synthea__encounters') }} as e
left join {{ ref('int_patients') }} as p
    on p.dataset_id = e.dataset_id and p.patient_id = e.patient_id
where p.patient_id is null

union all

-- Visit links: unresolved links are nulled but the event is kept; wrong-person links block publication.
select 'visit_link', encounter_link_status, 'conditions', source_event_key, null, 'star,omop',
       encounter_link_status = 'unresolved', encounter_link_status = 'wrong_person',
       source_batch_id, source_record_number
from {{ ref('int_conditions') }} where encounter_link_status in ('unresolved', 'wrong_person')
union all
select 'visit_link', encounter_link_status, 'medications', source_event_key, null, 'star,omop',
       encounter_link_status = 'unresolved', encounter_link_status = 'wrong_person',
       source_batch_id, source_record_number
from {{ ref('int_medications') }} where encounter_link_status in ('unresolved', 'wrong_person')
union all
select 'visit_link', encounter_link_status, 'observations', source_event_key, null, 'star,omop',
       encounter_link_status = 'unresolved', encounter_link_status = 'wrong_person',
       source_batch_id, source_record_number
from {{ ref('int_observations') }} where encounter_link_status in ('unresolved', 'wrong_person')

union all

-- MAP-03/04 routing exclusions (event kept in the star, not in OMOP).
select 'omop_routing', routing_exclusion_reason, source_file, source_event_key, null, 'omop',
       false, false, source_batch_id, source_record_number
from {{ ref('int_omop_event_candidates') }}
where routing_exclusion_reason is not null or proposed_destination is null

union all

-- OMOP person population.
select 'omop_person', op.exclusion_reason, 'patients', 'person', p.patient_pseudo_id, 'omop',
       false, false, p.source_batch_id, p.source_record_number
from {{ ref('int_omop_persons') }} as op
inner join {{ ref('int_patients') }} as p on p.patient_key = op.patient_key
where not op.is_included

union all

select 'omop_person', 'event of excluded person', e.source_file, e.source_event_key, null, 'omop',
       false, false, e.source_batch_id, e.source_record_number
from {{ ref('int_omop_events') }} as e
where not e.person_included

union all

select 'omop_death', 'death date after as-of date', 'patients', 'person', p.patient_pseudo_id, 'omop',
       false, false, p.source_batch_id, p.source_record_number
from {{ ref('int_patients') }} as p
cross join rev
where p.death_date > rev.as_of_date
