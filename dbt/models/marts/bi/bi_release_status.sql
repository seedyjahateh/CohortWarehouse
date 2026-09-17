-- Grain: exactly one row describing the candidate. Publication fills release_id, published_at and the
-- quality summary inside the release transaction (cohortwarehouse/publish.py).
with rev as (
    select * from {{ ref('stg_ops__selected_revision') }}
),

quarantine as (
    select count(*) as quarantined_rows
    from {{ source('ops', 'quarantine') }} as q
    inner join {{ source('ops', 'batch') }} as b on b.batch_id = q.batch_id
    cross join rev
    where b.dataset_id = rev.dataset_id and b.source_revision <= rev.target_revision
),

vocab as (
    select vocabulary_version, is_test_only
    from {{ source('ops', 'vocabulary_release') }}
    where is_current
)

select
    null::text as release_id,
    rev.run_id,
    rev.dataset_id,
    rev.target_batch_id as source_batch_id,
    rev.target_revision as source_revision,
    rev.as_of_date as source_as_of_date,
    rev.target_delivered_at as source_delivered_at_utc,
    now() as candidate_built_at_utc,
    null::timestamptz as published_at_utc,
    vocab.vocabulary_version,
    coalesce(vocab.is_test_only, true) as vocabulary_is_test_only,
    '5.4' as omop_cdm_version,
    '{{ git_sha() }}' as git_sha,
    quarantine.quarantined_rows,
    (select count(*) from {{ ref('int_exclusion_ledger') }} where not event_retained) as excluded_records,
    (select count(*) from {{ ref('bi_patient_snapshot') }}) as eligible_patients,
    null::integer as quality_checks_passed,
    null::integer as quality_checks_failed,
    null::integer as quality_checks_warned,
    'Synthetic data - demonstration only' as data_label
from rev
cross join quarantine
left join vocab on true
