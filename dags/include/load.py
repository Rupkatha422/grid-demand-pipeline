"""Load raw JSON files into DuckDB with idempotent upserts, and export the mart for the dashboard."""
import json
import logging
from datetime import datetime, timezone

import duckdb
import pandas as pd

from include import config

log = logging.getLogger(__name__)

DDL = """
create table if not exists raw_demand (
    period_utc   timestamp primary key,
    respondent   varchar,
    demand_mwh   double,
    loaded_at    timestamp
);
create table if not exists raw_weather (
    city         varchar,
    hour_utc     timestamp,
    temperature_c double,
    loaded_at    timestamp,
    primary key (city, hour_utc)
);
"""


def _demand_frame(path: str) -> pd.DataFrame:
    rows = json.loads(open(path).read())
    df = pd.DataFrame(rows, columns=["period", "respondent", "value"])
    return pd.DataFrame({
        "period_utc": pd.to_datetime(df["period"], format="%Y-%m-%dT%H"),
        "respondent": df["respondent"],
        "demand_mwh": pd.to_numeric(df["value"], errors="coerce"),
    }).dropna(subset=["demand_mwh"])


def _weather_frame(path: str) -> pd.DataFrame:
    frames = []
    for city in json.loads(open(path).read()):
        hourly = city["hourly"]
        frames.append(pd.DataFrame({
            "city": city["city"],
            "hour_utc": pd.to_datetime(hourly["time"]),
            "temperature_c": hourly["temperature_2m"],
        }))
    # Open-Meteo returns null for hours not yet in the archive; skip them so the watermark stays honest.
    return pd.concat(frames).dropna(subset=["temperature_c"])


def load_to_duckdb(demand_path: str, weather_path: str) -> dict:
    """Upsert both raw files. Re-running with the same files changes nothing (idempotent)."""
    demand = _demand_frame(demand_path)
    weather = _weather_frame(weather_path)
    loaded_at = datetime.now(timezone.utc).replace(tzinfo=None)

    with duckdb.connect(str(config.WAREHOUSE_PATH)) as con:
        con.execute(DDL)
        con.register("demand_df", demand)
        con.register("weather_df", weather)
        con.execute("""
            insert or replace into raw_demand
            select period_utc, respondent, demand_mwh, ? from demand_df
        """, [loaded_at])
        con.execute("""
            insert or replace into raw_weather
            select city, hour_utc, temperature_c, ? from weather_df
        """, [loaded_at])
        counts = {
            "demand_rows_in_file": len(demand),
            "weather_rows_in_file": len(weather),
            "raw_demand_total": con.execute("select count(*) from raw_demand").fetchone()[0],
            "raw_weather_total": con.execute("select count(*) from raw_weather").fetchone()[0],
        }
    log.info("Load complete: %s", counts)
    return counts


def export_for_dashboard() -> str:
    """Write the fct_hourly_demand mart to Parquet so the dashboard (and Streamlit Cloud) can read it."""
    config.EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = config.EXPORT_DIR / "fct_hourly_demand.parquet"
    with duckdb.connect(str(config.WAREHOUSE_PATH), read_only=True) as con:
        con.execute(f"copy (select * from fct_hourly_demand order by hour_utc) to '{out}' (format parquet)")
    log.info("Exported %s", out)
    return str(out)
