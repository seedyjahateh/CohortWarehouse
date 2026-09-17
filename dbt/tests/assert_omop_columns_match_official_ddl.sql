-- GOV-01: implemented CDM tables must match the pinned official OMOP 5.4 PostgreSQL DDL (loaded into
-- omop_ddl_ref at bootstrap) column-for-column: same names, same order-independent set, same data types.
-- No custom columns may appear inside official CDM tables. Zero rows = pass.
{% set cdm_tables = ['person', 'observation_period', 'visit_occurrence', 'condition_occurrence', 'drug_exposure',
                     'measurement', 'observation', 'death', 'cdm_source'] %}
with implemented as (
    select table_name, column_name,
           case when data_type = 'character varying' then 'varchar(' || character_maximum_length || ')'
                else data_type end as data_type
    from information_schema.columns
    where table_schema = '{{ ref("omop_person").schema }}'
      and table_name in ({% for t in cdm_tables %}'{{ t }}'{% if not loop.last %}, {% endif %}{% endfor %})
),

official as (
    select table_name, column_name,
           case when data_type = 'character varying' then 'varchar(' || character_maximum_length || ')'
                else data_type end as data_type
    from information_schema.columns
    where table_schema = 'omop_ddl_ref'
      and table_name in ({% for t in cdm_tables %}'{{ t }}'{% if not loop.last %}, {% endif %}{% endfor %})
)

-- depends_on: {{ ref('omop_person') }}
-- depends_on: {{ ref('omop_observation_period') }}
-- depends_on: {{ ref('omop_visit_occurrence') }}
-- depends_on: {{ ref('omop_condition_occurrence') }}
-- depends_on: {{ ref('omop_drug_exposure') }}
-- depends_on: {{ ref('omop_measurement') }}
-- depends_on: {{ ref('omop_observation') }}
-- depends_on: {{ ref('omop_death') }}
-- depends_on: {{ ref('omop_cdm_source') }}
(select 'not_in_official_ddl' as problem, * from implemented except select 'not_in_official_ddl', * from official)
union all
(select 'missing_or_retyped', * from official except select 'missing_or_retyped', * from implemented)
