# Airflow 3 runtime with dbt isolated in its own virtual environment so Airflow's
# constraint set and dbt's dependency tree never have to agree.
FROM apache/airflow:3.1.0-python3.12@sha256:e81cb98fe4e5f60fadde8cc6a1c926a363720339062cd53db04b6442950ab9ee

USER root
COPY requirements/dbt.lock /tmp/dbt.lock
RUN python -m venv /opt/dbt-venv \
    && /opt/dbt-venv/bin/pip install --no-cache-dir -r /tmp/dbt.lock \
    && chown -R airflow:0 /opt/dbt-venv

COPY --chown=airflow:0 pyproject.toml /opt/cohortwarehouse/pyproject.toml
COPY --chown=airflow:0 cohortwarehouse /opt/cohortwarehouse/cohortwarehouse
COPY --chown=airflow:0 config /opt/cohortwarehouse/config
COPY --chown=airflow:0 sql /opt/cohortwarehouse/sql
COPY --chown=airflow:0 dbt /opt/cohortwarehouse/dbt

USER airflow
# The CLI package only needs psycopg/PyYAML/jsonschema; install against Airflow's constraints.
RUN pip install --no-cache-dir \
      --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-3.1.0/constraints-3.12.txt" \
      "psycopg[binary]" PyYAML jsonschema \
    && pip install --no-cache-dir --no-deps /opt/cohortwarehouse

ENV CW_REPO_ROOT=/opt/cohortwarehouse
