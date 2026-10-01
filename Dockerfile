FROM apache/airflow:3.3.2

# Pipeline libraries, installed into Airflow's own environment.
# DuckDB is pinned so the Airflow tasks and dbt read and write the same file format.
RUN pip install --no-cache-dir \
    "apache-airflow==${AIRFLOW_VERSION}" \
    duckdb==1.5.6 \
    requests \
    pandas \
    pyarrow

# dbt goes in its own virtualenv so its dependencies can't conflict with Airflow's.
RUN python -m venv /home/airflow/dbt_venv \
 && /home/airflow/dbt_venv/bin/pip install --no-cache-dir dbt-duckdb==1.11.0 duckdb==1.5.6
