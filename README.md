# CohortWarehouse
An end-to-end analytics pipeline that ingests synthetic EHR/research data (Synthea-generated), loads it into a warehouse (Postgres/DuckDB or Snowflake free tier), transforms it with dbt into a Kimball star schema AND an OMOP Common Data Model mart, orchestrates with Airflow, and surfaces cohort-discovery dashboards in Power BI or Tableau.
