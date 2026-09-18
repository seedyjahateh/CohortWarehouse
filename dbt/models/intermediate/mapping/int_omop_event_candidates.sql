{{
    config(
        materialized='incremental',
        incremental_strategy='append',
        on_schema_change='fail',
        pre_hook=["{{ delete_changed_person_slice('patient_id', via='patient_id') }}"],
        indexes=[{'columns': ['patient_id']}]
    )
}}
-- depends_on: {{ ref('int_changed_person') }}
-- Grain: one (source clinical event with a valid patient, mapping ordinal). One-to-many mappings fan out
-- here and nowhere else. Routing is by TARGET domain (MAP-03), independent of the input file;
-- unmapped events use the source-contract routing seed (MAP-04) or enter the exclusion ledger.
-- Incremental by changed person (keyed on source patient id: built before key registration).
with events as (
    select * from {{ ref('int_clinical_events') }}
    where patient_exists
    {% if is_incremental() %}
      and patient_id in {{ changed_person_subquery('patient_id') }}
    {% endif %}
),

mapped as (
    select
        e.*,
        coalesce(m.mapping_ordinal, 1) as mapping_ordinal,
        coalesce(m.target_concept_id, 0) as target_concept_id,
        m.target_domain_id,
        coalesce(m.source_concept_id, 0) as source_concept_id,
        m.value_as_concept_id,
        coalesce(m.value_map_count, 0) as value_map_count,
        coalesce(m.target_count, 0) as target_count,
        case when e.source_vocabulary_id is null then 'unresolved_vocabulary' else m.mapping_status end
            as mapping_status
    from events as e
    left join {{ ref('int_concept_map') }} as m
        on m.source_vocabulary_id = e.source_vocabulary_id
       and m.source_code = e.source_code
),

routed as (
    select
        mapped.*,
        case
            when target_concept_id <> 0 then
                case target_domain_id
                    when 'Condition' then 'condition_occurrence'
                    when 'Drug' then 'drug_exposure'
                    when 'Measurement' then 'measurement'
                    when 'Observation' then 'observation'
                end
            else coalesce(specific.destination_table, generic.destination_table)
        end as proposed_destination
    from mapped
    left join {{ ref('unmapped_routing') }} as specific
        on specific.source_file = mapped.source_file
       and specific.source_category = mapped.source_category
    left join {{ ref('unmapped_routing') }} as generic
        on generic.source_file = mapped.source_file
       and generic.source_category = '(any)'
)

select
    routed.*,
    case
        when value_map_count > 1 then 'ambiguous_maps_to_value'
        when value_map_count = 1 and proposed_destination not in ('measurement', 'observation')
            then 'maps_to_value_unsupported_destination'
        when proposed_destination is null and target_concept_id <> 0
            then 'unsupported_target_domain:' || coalesce(target_domain_id, '(none)')
        when proposed_destination is null then 'ambiguous_unmapped_domain'
    end as routing_exclusion_reason,
    coalesce(
        target_concept_id <> 0
        and proposed_destination is not null
        and value_map_count <= 1
        and (value_map_count = 0 or proposed_destination in ('measurement', 'observation')),
        false
    ) as has_valid_supported_mapping,
    source_event_key || '|' || coalesce(proposed_destination, 'excluded') || '|'
        || target_concept_id::text || '|' || mapping_ordinal::text as omop_event_natural_key
from routed
