"""Daily ELT for PJM electricity demand and weather: extract -> DuckDB -> dbt -> dashboard export -> AI briefing."""
from datetime import datetime, timedelta

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import dag, task

DBT = "/home/airflow/dbt_venv/bin/dbt"
DBT_DIR = "/opt/airflow/dbt"


@dag(
    schedule="@daily",
    start_date=datetime(2026, 9, 1),
    catchup=False,
    max_active_runs=1,  # DuckDB allows one writer at a time
    default_args={"retries": 2, "retry_delay": timedelta(minutes=5)},
    tags=["grid", "elt"],
    doc_md=__doc__,
)
def grid_demand_pipeline():

    @task
    def fetch_eia_demand() -> str:
        from include.extract import fetch_eia_demand
        return fetch_eia_demand()

    @task
    def fetch_weather() -> str:
        from include.extract import fetch_weather
        return fetch_weather()

    @task
    def load_to_duckdb(demand_path: str, weather_path: str) -> dict:
        from include.load import load_to_duckdb
        return load_to_duckdb(demand_path, weather_path)

    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=f"cd {DBT_DIR} && {DBT} build --profiles-dir {DBT_DIR} --project-dir {DBT_DIR}",
    )

    @task
    def export_for_dashboard() -> str:
        from include.load import export_for_dashboard
        return export_for_dashboard()

    @task
    def write_ai_briefing() -> str:
        from airflow.exceptions import AirflowSkipException
        from include import llm
        from include.briefing import write_briefing
        if not llm.api_key():
            raise AirflowSkipException("GROQ_API_KEY not set; skipping the AI briefing.")
        return write_briefing()

    loaded = load_to_duckdb(fetch_eia_demand(), fetch_weather())
    loaded >> dbt_build >> export_for_dashboard() >> write_ai_briefing()


grid_demand_pipeline()
