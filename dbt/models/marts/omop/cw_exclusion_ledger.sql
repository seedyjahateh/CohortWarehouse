-- NOT a CDM table (cw_ prefix). Grain: one (source record or person, exclusion reason) for the selected
-- revision; published with the OMOP release so reviewers can reconcile source to target (STG-05).
select * from {{ ref('int_exclusion_ledger') }}
