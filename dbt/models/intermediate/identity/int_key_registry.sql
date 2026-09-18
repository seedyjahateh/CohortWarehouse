{#- Registers natural keys in the persistent ops.entity_key_map before any keyed model is built.
    Person-linked entities are registered only for changed people: unchanged people were registered by
    the build that recorded their fingerprint. Small reference entities are registered in full.
    Hooks are rendered at execution time (queries live in macros/key_registration.sql). -#}
{{
    config(
        materialized='table',
        pre_hook=[
            "{{ register_natural_keys('patient', key_registration_query('patient')) }}",
            "{{ register_natural_keys('organization', key_registration_query('organization')) }}",
            "{{ register_natural_keys('encounter_type', key_registration_query('encounter_type')) }}",
            "{{ register_natural_keys('encounter', key_registration_query('encounter')) }}",
            "{{ register_natural_keys('condition', key_registration_query('condition')) }}",
            "{{ register_natural_keys('medication', key_registration_query('medication')) }}",
            "{{ register_natural_keys('observation', key_registration_query('observation')) }}",
            "{{ register_natural_keys('clinical_code', key_registration_query('clinical_code')) }}",
            "{{ register_natural_keys('unit', key_registration_query('unit')) }}",
            "{{ register_natural_keys('omop_event', key_registration_query('omop_event')) }}",
        ],
        post_hook=["select ops.analyze_key_registry()"]
    )
}}
-- depends_on: {{ ref('int_changed_person') }}
-- depends_on: {{ ref('stg_synthea__patients') }}
-- depends_on: {{ ref('stg_synthea__organizations') }}
-- depends_on: {{ ref('stg_synthea__encounters') }}
-- depends_on: {{ ref('encounter_classes') }}
-- depends_on: {{ ref('int_condition_events') }}
-- depends_on: {{ ref('int_medication_events') }}
-- depends_on: {{ ref('int_observation_events') }}
-- depends_on: {{ ref('int_omop_event_candidates') }}
-- Grain: one entity type; registry size for the selected dataset after this run's registrations.
select
    m.entity_type,
    count(*) as registered_keys,
    count(*) filter (where m.first_run_id = '{{ run_id() }}') as registered_this_run,
    max(m.surrogate_id) as max_surrogate_id
from {{ source('ops', 'entity_key_map') }} as m
inner join {{ ref('stg_ops__selected_revision') }} as rev
    on rev.dataset_id = m.dataset_id
group by m.entity_type
