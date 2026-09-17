-- Least privilege (Section 10). Re-applied after raw tables are (re)generated.

-- ------------------------------------------------------------ loader: writes raw + batch audit
grant usage on schema raw, ops to cwr_loader;
grant select, insert, delete on all tables in schema raw to cwr_loader;
grant select on ops.batch, ops.batch_file, ops.batch_scope_patient, ops.quarantine to cwr_loader;
grant insert on ops.batch, ops.batch_file, ops.batch_scope_patient, ops.quarantine to cwr_loader;
grant select, insert, update on ops.load_attempt, ops.alert_event to cwr_loader;
grant usage on sequence ops.quarantine_quarantine_id_seq, ops.load_attempt_attempt_id_seq,
    ops.alert_event_alert_id_seq to cwr_loader;

grant execute on function ops.analyze_raw() to cwr_loader;

-- ------------------------------------------------------------ transformer: reads raw, writes candidates
grant usage on schema raw, ops, vocab, omop_ddl_ref to cwr_transformer;
grant select on all tables in schema raw, vocab, omop_ddl_ref to cwr_transformer;
grant select on all tables in schema ops to cwr_transformer;
grant insert, update on ops.entity_key_map, ops.person_state_built, ops.pending_person,
    ops.build_state, ops.pipeline_run, ops.quality_result, ops.alert_event, ops.candidate_owner to cwr_transformer;
grant delete on ops.person_state_built, ops.pending_person, ops.quality_result to cwr_transformer;
grant usage on sequence ops.entity_key_seq, ops.alert_event_alert_id_seq to cwr_transformer;

-- ------------------------------------------------------------ publisher: owns releases and stable views
grant usage on schema ops, vocab, omop_ddl_ref, "int", work_star, work_omop, work_bi to cwr_publisher;
grant select on all tables in schema ops, vocab, omop_ddl_ref to cwr_publisher;
grant insert, update on ops.release, ops.current_release, ops.release_event, ops.report_pin,
    ops.alert_event to cwr_publisher;
grant delete on ops.report_pin to cwr_publisher;
grant update (status, finished_at, error_class, error_message) on ops.pipeline_run to cwr_publisher;
grant usage on sequence ops.release_event_event_id_seq, ops.alert_event_alert_id_seq to cwr_publisher;
alter default privileges for role cwr_transformer in schema "int", work_star, work_omop, work_bi
    grant select on tables to cwr_publisher;
grant select on all tables in schema "int", work_star, work_omop, work_bi to cwr_publisher;

-- ------------------------------------------------------------ BI reader: published BI only (US-08)
grant usage on schema bi to cwr_bi_reader;
alter default privileges for role cwr_publisher in schema bi grant select on tables to cwr_bi_reader;
grant select on all tables in schema bi to cwr_bi_reader;

-- ------------------------------------------------------------ OMOP reader: published OMOP + vocabulary
grant usage on schema omop, vocab to cwr_omop_reader;
grant select on all tables in schema vocab to cwr_omop_reader;
alter default privileges for role cwr_publisher in schema omop grant select on tables to cwr_omop_reader;
grant select on all tables in schema omop to cwr_omop_reader;

-- Neither reader role may touch raw, ops, staging or candidate schemas; nothing grants it,
-- and tests/integration/test_access.py proves the denials.
