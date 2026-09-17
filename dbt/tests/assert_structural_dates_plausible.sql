-- Temporal rules (Section 11.1), blocking only for structurally impossible dates: an event starting before
-- birth, or a death before birth. Contextual oddities (events after death, events after D) are profiled in
-- bi_data_profile rather than blocked. End-before-start checks are generic tests in the YAML. Zero rows = pass.
with events as (
    select patient_key, 'encounter' as kind, start_date from {{ ref('int_encounters') }}
    union all select patient_key, 'condition', start_date from {{ ref('int_conditions') }}
    union all select patient_key, 'medication', start_date from {{ ref('int_medications') }}
    union all select patient_key, 'observation', observation_date from {{ ref('int_observations') }}
)

select 'event_before_birth' as problem, e.kind, count(*) as rows_affected
from events as e
inner join {{ ref('int_patients') }} as p on p.patient_key = e.patient_key
where e.start_date < p.birth_date
group by e.kind

union all

select 'death_before_birth', 'patient', count(*)
from {{ ref('int_patients') }}
where death_date < birth_date
having count(*) > 0
