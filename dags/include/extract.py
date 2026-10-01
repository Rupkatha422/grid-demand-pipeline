"""Extract hourly PJM demand (EIA) and weather (Open-Meteo), saving raw JSON to data/raw/.

Run by hand to test:  python -m include.extract   (from the dags/ folder)
"""
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import duckdb
import requests

from include import config

log = logging.getLogger(__name__)


def get_watermark(table: str, ts_column: str) -> datetime | None:
    """Return the latest timestamp already loaded, or None if the warehouse is empty."""
    if not config.WAREHOUSE_PATH.exists():
        return None
    with duckdb.connect(str(config.WAREHOUSE_PATH), read_only=True) as con:
        exists = con.execute(
            "select count(*) from information_schema.tables where table_name = ?", [table]
        ).fetchone()[0]
        if not exists:
            return None
        return con.execute(f"select max({ts_column}) from {table}").fetchone()[0]


def _start_from(watermark: datetime | None) -> datetime:
    """Incremental start: a little before the watermark, or a full backfill if there is none."""
    if watermark is None:
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
        return today - timedelta(days=365 * config.BACKFILL_YEARS)
    return watermark - timedelta(hours=config.OVERLAP_HOURS)


def _save_raw(name: str, payload) -> str:
    """Write a raw response to data/raw/YYYY-MM-DD/<name>_<timestamp>.json and return the path."""
    now = datetime.now(timezone.utc)
    folder = config.RAW_DIR / now.strftime("%Y-%m-%d")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}_{now.strftime('%H%M%S')}.json"
    path.write_text(json.dumps(payload))
    log.info("Saved %s", path)
    return str(path)


def fetch_eia_demand(start: datetime | None = None, end: datetime | None = None) -> str:
    """Fetch hourly PJM demand (type D) in UTC, paging through EIA's 5,000-row limit."""
    if not config.EIA_API_KEY:
        raise RuntimeError("EIA_API_KEY is not set. Add it to .env and restart the containers.")

    start = start or _start_from(get_watermark("raw_demand", "period_utc"))
    end = end or datetime.now(timezone.utc).replace(tzinfo=None)
    log.info("Fetching EIA demand from %s to %s", start, end)

    rows, offset = [], 0
    while True:
        params = {
            "api_key": config.EIA_API_KEY,
            "frequency": "hourly",  # UTC hours; "local-hourly" would be Eastern time
            "data[0]": "value",
            "facets[respondent][]": config.EIA_RESPONDENT,
            "facets[type][]": "D",
            "start": start.strftime("%Y-%m-%dT%H"),
            "end": end.strftime("%Y-%m-%dT%H"),
            "sort[0][column]": "period",
            "sort[0][direction]": "asc",
            "offset": offset,
            "length": config.EIA_PAGE_SIZE,
        }
        resp = requests.get(config.EIA_URL, params=params, timeout=60)
        resp.raise_for_status()
        page = resp.json()["response"]["data"]
        rows.extend(page)
        log.info("EIA page at offset %d: %d rows", offset, len(page))
        if len(page) < config.EIA_PAGE_SIZE:
            break
        offset += config.EIA_PAGE_SIZE

    return _save_raw("eia_demand", rows)


def fetch_weather(start: date | None = None, end: date | None = None) -> str:
    """Fetch hourly temperature (UTC) for each city from the Open-Meteo archive.

    The archive lags real time by a few days, so the most recent hours come back as null;
    the loader skips those and the next run picks them up.
    """
    if start is None:
        start = _start_from(get_watermark("raw_weather", "hour_utc")).date()
    end = end or datetime.now(timezone.utc).date()
    log.info("Fetching weather from %s to %s", start, end)

    names = list(config.CITIES)
    params = {
        "latitude": ",".join(str(config.CITIES[c][0]) for c in names),
        "longitude": ",".join(str(config.CITIES[c][1]) for c in names),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "hourly": "temperature_2m",
        "timezone": "UTC",
    }
    resp = requests.get(config.WEATHER_URL, params=params, timeout=120)
    resp.raise_for_status()
    body = resp.json()
    # One location returns a dict; several return a list in the same order as the request.
    results = body if isinstance(body, list) else [body]
    payload = [{"city": name, **result} for name, result in zip(names, results)]
    return _save_raw("weather", payload)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(fetch_eia_demand())
    print(fetch_weather())
