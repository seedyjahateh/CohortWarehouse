-- Operational metadata: manifests, reconciliation, key registry, runs, quality, releases.
-- Idempotent: safe to re-apply.

create table if not exists ops.schema_migration (
    filename    text primary key,
    sha256      text not null,
    applied_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------- batches (ING-01..07)
create table if not exists ops.batch (
    batch_id            text primary key,
    dataset_id          text not null,
    source_revision     integer not null check (source_revision > 0),
    as_of_date          date not null,
    delivered_at        timestamptz not null,
    delivery_kind       text not null default 'manual',
    replacement_mode    text not null check (replacement_mode in ('full', 'scoped')),
    manifest            jsonb not null,
    manifest_sha256     text not null,
    generator_name      text not null,
    generator_version   text not null,
    synthetic           boolean not null check (synthetic),
    scope_accounting    jsonb not null default '{}'::jsonb,
    loaded_at           timestamptz not null default now(),
    loaded_by           text not null default session_user,
    unique (dataset_id, source_revision)
);

create table if not exists ops.batch_file (
    batch_id                 text not null references ops.batch (batch_id),
    file_key                 text not null,
    filename                 text not null,
    sha256                   text not null,
    size_bytes               bigint not null,
    header                   jsonb not null,
    extra_columns            jsonb not null,
    missing_optional_columns jsonb not null,
    unloaded_columns         jsonb not null,
    declared_records         integer not null,
    parsed_records           integer not null,
    accepted_records         integer not null,
    quarantined_records      integer not null,
    load_seconds             numeric(12, 3),
    primary key (batch_id, file_key),
    -- ING-06: parsed = accepted + quarantined, and parsed must equal the manifest declaration.
    constraint batch_file_reconciles check (parsed_records = accepted_records + quarantined_records),
    constraint batch_file_matches_manifest check (parsed_records = declared_records)
);

create table if not exists ops.batch_scope_patient (
    batch_id    text not null references ops.batch (batch_id),
    patient_id  text not null,
    primary key (batch_id, patient_id)
);
create index if not exists batch_scope_patient_patient on ops.batch_scope_patient (patient_id);

create table if not exists ops.quarantine (
    quarantine_id   bigserial primary key,
    dataset_id      text not null,
    batch_id        text not null references ops.batch (batch_id),
    file_key        text not null,
    record_number   integer not null,
    file_sha256     text not null,
    reason          text not null,
    detail          text,
    row_fingerprint text,
    payload         jsonb,          -- restricted: raw field values; 30-day retention
    ingested_at     timestamptz not null default now(),
    unique (batch_id, file_key, record_number, reason)
);

create table if not exists ops.load_attempt (
    attempt_id      bigserial primary key,
    batch_id        text,
    dataset_id      text,
    manifest_path   text not null,
    manifest_sha256 text,
    started_at      timestamptz not null default now(),
    finished_at     timestamptz,
    outcome         text check (outcome in ('loaded', 'already_loaded', 'rejected', 'failed')),
    error_class     text,
    error_message   text
);

-- Raw tables are owned by the administrator (the loader cannot drop or alter them), so statistics are
-- refreshed through this narrowly scoped SECURITY DEFINER function after each load.
create or replace function ops.analyze_raw() returns void
language plpgsql security definer set search_path = pg_catalog as $$
declare
    t record;
begin
    for t in select tablename from pg_tables where schemaname = 'raw' loop
        execute format('analyze raw.%I', t.tablename);
    end loop;
end
$$;
revoke all on function ops.analyze_raw() from public;

-- Same for the key registry, which the transformer fills through dbt pre-hooks but does not own. Without
-- fresh statistics the planner joins a multi-million-row registry as if it held a single row.
create or replace function ops.analyze_key_registry() returns void
language plpgsql security definer set search_path = pg_catalog as $$
begin
    execute 'analyze ops.entity_key_map';
end
$$;
revoke all on function ops.analyze_key_registry() from public;

-- ---------------------------------------------------------------- vocabulary provenance
create table if not exists ops.vocabulary_release (
    vocabulary_version  text primary key,
    source_kind         text not null check (source_kind in ('athena', 'test_fictional')),
    is_test_only        boolean not null,
    file_hashes         jsonb not null,
    row_counts          jsonb not null,
    license_note        text not null,
    loaded_at           timestamptz not null default now(),
    loaded_by           text not null default session_user,
    is_current          boolean not null default false
);
create unique index if not exists vocabulary_release_one_current
    on ops.vocabulary_release (is_current) where is_current;

-- ---------------------------------------------------------------- key registry (Section 8.4)
create sequence if not exists ops.entity_key_seq as integer start with 1 minvalue 1;

create table if not exists ops.entity_key_map (
    entity_type        text not null,
    dataset_id         text not null,
    natural_key        text not null,
    surrogate_id       integer not null default nextval('ops.entity_key_seq'),
    canonical_content  text,
    first_run_id       text,
    created_at         timestamptz not null default now(),
    primary key (entity_type, dataset_id, natural_key),
    unique (entity_type, surrogate_id),
    check (surrogate_id > 0)   -- 0 is reserved for Unknown star members
);

-- ---------------------------------------------------------------- runs and incremental state
create table if not exists ops.pipeline_run (
    run_id              text primary key,
    dataset_id          text not null,
    target_batch_id     text not null references ops.batch (batch_id),
    target_revision     integer not null,
    as_of_date          date not null,
    mode                text not null check (mode in ('incremental', 'full_refresh', 'validation_only')),
    full_refresh_reason text,
    build_fingerprint   text not null,
    vocabulary_version  text,
    git_sha             text,
    trigger             text not null default 'cli',
    status              text not null check (status in ('started', 'built', 'validated', 'failed', 'published')),
    started_at          timestamptz not null default now(),
    built_at            timestamptz,
    validated_at        timestamptz,
    finished_at         timestamptz,
    error_class         text,
    error_message       text,
    stage_timings       jsonb not null default '{}'::jsonb,
    counts              jsonb not null default '{}'::jsonb
);

-- Last successfully *built* candidate state per person. Change detection compares against
-- this (not against the published release) so a failed or unpublished build can never
-- leave a stale slice behind. See docs/decisions/0003-change-detection-baseline.md.
create table if not exists ops.person_state_built (
    dataset_id          text not null,
    patient_id          text not null,
    person_fingerprint  text not null,
    source_revision     integer not null,
    run_id              text not null,
    primary key (dataset_id, patient_id)
);

-- People whose slices may be partially rewritten by an attempt that did not finish.
create table if not exists ops.pending_person (
    dataset_id  text not null,
    patient_id  text not null,
    run_id      text not null,
    added_at    timestamptz not null default now(),
    primary key (dataset_id, patient_id)
);

create table if not exists ops.build_state (
    dataset_id          text primary key,
    run_id              text not null,
    source_revision     integer not null,
    build_fingerprint   text not null,
    vocabulary_version  text,
    built_at            timestamptz not null
);

-- Reference-data fingerprint (organization id set): a change forces a full refresh because
-- unchanged people's facts may reference organizations that appeared or disappeared.
alter table ops.pipeline_run add column if not exists reference_fingerprint text;
alter table ops.build_state add column if not exists reference_fingerprint text;
alter table ops.build_state add column if not exists as_of_date date;

-- Which dataset last WROTE to the shared candidate schemas (set when a build stage starts, not when it
-- succeeds). A different owner forces a full refresh even if that other build failed half-way.
create table if not exists ops.candidate_owner (
    singleton   boolean primary key default true check (singleton),
    dataset_id  text not null,
    run_id      text not null,
    updated_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------- quality
create table if not exists ops.quality_result (
    run_id      text not null references ops.pipeline_run (run_id),
    check_id    text not null,
    category    text not null,
    severity    text not null check (severity in ('blocking', 'warning')),
    status      text not null check (status in ('pass', 'fail', 'skip', 'warn')),
    observed    numeric,
    threshold   text,
    detail      jsonb not null default '{}'::jsonb,
    checked_at  timestamptz not null default now(),
    primary key (run_id, check_id)
);

-- ---------------------------------------------------------------- releases (Section 9.4)
create table if not exists ops.release (
    release_id          text primary key,
    release_number      integer not null unique,
    dataset_id          text not null,
    run_id              text not null references ops.pipeline_run (run_id),
    source_revision     integer not null,
    source_batch_id     text not null,
    as_of_date          date not null,
    vocabulary_version  text,
    build_fingerprint   text not null,
    git_sha             text,
    star_schema         text not null,
    omop_schema         text not null,
    bi_schema           text not null,
    table_checksums     jsonb not null,
    status              text not null check (status in ('published', 'dropped')),
    published_at        timestamptz not null default now(),
    published_by        text not null default session_user,
    dropped_at          timestamptz
);

-- Which validation profile certified the run behind a release: only `release` (pinned real vocabulary)
-- certifies a release; `fixture` runs are exercises on the fictional test vocabulary.
alter table ops.release add column if not exists validation_profile text;

create table if not exists ops.current_release (
    dataset_id   text primary key,
    release_id   text not null references ops.release (release_id),
    previous_release_id text references ops.release (release_id),
    switched_at  timestamptz not null default now(),
    switched_by  text not null default session_user,
    reason       text not null
);

create table if not exists ops.release_event (
    event_id    bigserial primary key,
    dataset_id  text not null,
    release_id  text,
    run_id      text,
    event       text not null check (event in (
                    'published', 'restored', 'publish_failed', 'restore_failed',
                    'docs_incomplete', 'docs_generated', 'dropped')),
    detail      jsonb not null default '{}'::jsonb,
    at          timestamptz not null default now(),
    actor       text not null default session_user
);

-- Releases a Power BI report imports from; cleanup refuses to drop them.
create table if not exists ops.report_pin (
    release_id  text not null references ops.release (release_id),
    report_name text not null,
    pinned_at   timestamptz not null default now(),
    primary key (release_id, report_name)
);

create table if not exists ops.alert_event (
    alert_id    bigserial primary key,
    dataset_id  text,
    run_id      text,
    source      text not null,
    severity    text not null check (severity in ('info', 'warning', 'error')),
    message     text not null,
    detail      jsonb not null default '{}'::jsonb,
    at          timestamptz not null default now()
);
