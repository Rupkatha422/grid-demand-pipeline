"""Shared settings for the grid demand pipeline."""
import os
from pathlib import Path

# Inside Docker this is /opt/airflow/data; locally it falls back to <repo>/data.
DATA_DIR = Path(os.getenv("GRID_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
RAW_DIR = DATA_DIR / "raw"
EXPORT_DIR = DATA_DIR / "exports"
WAREHOUSE_PATH = DATA_DIR / "warehouse.duckdb"

EIA_API_KEY = os.getenv("EIA_API_KEY", "")
EIA_URL = "https://api.eia.gov/v2/electricity/rto/region-data/data/"
EIA_RESPONDENT = "PJM"
EIA_PAGE_SIZE = 5000  # EIA's maximum rows per request

WEATHER_URL = "https://archive-api.open-meteo.com/v1/archive"
# Population centers inside the PJM footprint.
CITIES = {
    "philadelphia": (39.9526, -75.1652),
    "newark": (40.7357, -74.1724),
    "washington_dc": (38.9072, -77.0369),
}

# How far back the first run (empty warehouse) goes.
BACKFILL_YEARS = 3
# Re-fetch this many hours before the watermark, because EIA revises recent values.
# The upsert in load.py makes the overlap harmless.
OVERLAP_HOURS = 48
