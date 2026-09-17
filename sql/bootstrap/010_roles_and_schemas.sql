-- Group roles own objects and carry privileges. Login users (names from the environment)
-- are members and start every session as their group role (ALTER ROLE ... SET role), so
-- objects are owned by the group, not by an individual login.
do $$
declare
    r text;
begin
    foreach r in array array['cwr_loader', 'cwr_transformer', 'cwr_publisher', 'cwr_bi_reader', 'cwr_omop_reader']
    loop
        if not exists (select 1 from pg_roles where rolname = r) then
            execute format('create role %I nologin', r);
        end if;
    end loop;
end
$$;

-- Nobody gets implicit rights.
revoke all on schema public from public;
do $$ begin execute format('revoke all on database %I from public', current_database()); end $$;
do $$
declare
    r text;
begin
    foreach r in array array['cwr_loader', 'cwr_transformer', 'cwr_publisher', 'cwr_bi_reader', 'cwr_omop_reader']
    loop
        execute format('grant connect on database %I to %I', current_database(), r);
    end loop;
    -- Release schemas (star_rNNNN, omop_rNNNN, bi_rNNNN) are created at publication.
    execute format('grant create on database %I to cwr_publisher', current_database());
    -- dbt incremental materialisations stage rows in temporary tables.
    execute format('grant temporary on database %I to cwr_transformer', current_database());
end
$$;

-- Administrator-owned: immutable source batches, operational metadata, vocabularies.
create schema if not exists raw;
create schema if not exists ops;
create schema if not exists vocab;
create schema if not exists omop_ddl_ref;   -- official CDM DDL, used for contract comparison

-- Transformer-owned private candidates.
create schema if not exists stg       authorization cwr_transformer;
create schema if not exists "int"     authorization cwr_transformer;
create schema if not exists seeds     authorization cwr_transformer;
create schema if not exists work_star authorization cwr_transformer;
create schema if not exists work_omop authorization cwr_transformer;
create schema if not exists work_bi   authorization cwr_transformer;
create schema if not exists work_audit authorization cwr_transformer;  -- dbt --store-failures

-- Publisher-owned stable consumer views.
create schema if not exists star authorization cwr_publisher;
create schema if not exists omop authorization cwr_publisher;
create schema if not exists bi   authorization cwr_publisher;
