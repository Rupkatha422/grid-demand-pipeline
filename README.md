# US Electricity Grid Demand Pipeline

**Question:** How much does heat drive power demand on the PJM grid (which serves New Jersey and 12 other states)?

**Answer:** A lot. Across 3 years of hourly data (Oct 2023 to Sep 2026, 26,236 hours):
- Above 65°F, **every extra 1°F adds about 1,970 MWh** of demand per hour.
- Hours at or above 85°F draw **54% more power** than mild 60–70°F hours (130,900 vs. 85,300 MWh).
- The record hour was **162,648 MWh at 6 PM Eastern on July 2, 2026**, when the PJM-area average temperature was **101°F**.
- Cold matters too: below 50°F, each 1°F colder adds about 1,140 MWh, mostly from electric heating.

A Dockerized ELT pipeline, orchestrated by Apache Airflow, that ingests hourly grid demand (EIA API) and weather (Open-Meteo), loads it into DuckDB, models and tests it with dbt, and serves a Streamlit dashboard with two AI features powered by an open-weight LLM (gpt-oss-120b) on Groq: a daily briefing, and an assistant that answers questions in plain English. Infrastructure cost: $0.

## Architecture

```
Airflow DAG (daily)
  fetch_eia_demand ─┐
                    ├─> load_to_duckdb ─> dbt_build (models + tests) ─> export_for_dashboard ─> Streamlit
  fetch_weather ────┘                                                        └─> write_ai_briefing (LLM via Groq)
        │                    │
  data/raw/YYYY-MM-DD/   data/warehouse.duckdb
     (raw JSON)
```

_TODO: add a screenshot of the Airflow graph view to `docs/` and link it here._

## Tech stack

| Tool | Why |
|---|---|
| **Apache Airflow 3** (Docker Compose) | Scheduling, retries, dependency management and a UI to inspect runs |
| **DuckDB** | An analytical warehouse in a single file. The data is about 26k rows per year, so Spark or a cloud warehouse would be overkill |
| **dbt** (dbt-duckdb) | SQL transformations in layers (staging → intermediate → marts) with built-in data tests |
| **Streamlit + Altair** | A dashboard in pure Python, deployable for free on Streamlit Community Cloud |
| **gpt-oss-120b on Groq** | Fast, free-tier LLM inference for the briefing and the text-to-SQL assistant |
| **EIA API v2, Open-Meteo** | Free, official data sources (Open-Meteo needs no key) |

## Pipeline design

- **Incremental loading:** each run fetches only data after the latest timestamp in the warehouse (the *watermark*), minus a 48-hour overlap because EIA revises recent values.
- **Automatic backfill:** if the warehouse is empty, the first run loads the last 3 years.
- **Idempotent loads:** raw tables have primary keys, and loads use `INSERT OR REPLACE`, so re-running a day never creates duplicates.
- **Raw data kept:** every API response is saved to `data/raw/YYYY-MM-DD/` before loading, so any day can be reprocessed.
- **Time zones:** stored in UTC, with Eastern local time derived in staging (daylight saving handled by DuckDB).

## dbt models

| Layer | Model | Purpose |
|---|---|---|
| Staging | `stg_demand`, `stg_weather` | Rename columns, cast types, convert UTC to Eastern time, °C to °F |
| Intermediate | `int_weather_hourly_avg` | Average temperature across Philadelphia, Newark and Washington DC per hour |
| Marts | `fct_hourly_demand` | Demand joined to temperature, plus cooling/heating degree-hours |
| Marts | `dim_date` | Calendar attributes: season, weekday/weekend |

## Data quality

24 tests run on every `dbt build`. If one fails, the DAG stops before bad data reaches the dashboard.

| Test | What it catches |
|---|---|
| `unique` / `not_null` on every timestamp key | Duplicate or missing rows from a bad load |
| `unique_combination(city, hour_utc)` (custom) | Duplicate weather readings |
| `accepted_range` on demand (20k–200k MWh) and temperature (-30 to 120°F) (custom) | Unit errors and garbage values from the API |
| `assert_no_missing_demand_hours` (custom) | Gaps in the hourly series. Warns for any gap and fails for more than 24 missing hours. Documented source gaps in the `known_demand_gaps` seed are excluded |
| `relationships` fct → dim_date | Orphaned dates |
| Source freshness on `raw_demand` | The pipeline silently stopped loading |

## AI features

**AI daily briefing.** The last DAG task computes the facts for the latest full day in SQL: the peak and when it happened, the comparison with the same weekday over the previous 4 weeks, the comparison with days of similar temperature, and the peak's rank over the past year. The LLM then turns those facts into a headline and a short summary, and the dashboard shows it at the top. The model is told to use only the numbers it's given, so it can't make up figures. If `GROQ_API_KEY` isn't set, this task is skipped and the rest of the pipeline still runs.

**Ask the grid.** A chat tab that answers questions like *"Which day of the week uses the most power in summer?"* The LLM writes the DuckDB SQL, the dashboard runs it, and the LLM explains the result. Every answer shows the SQL and the data behind it. Guardrails:
- Queries run against an **in-memory copy** of the mart, with DuckDB's file and network access disabled and the setting locked.
- Only single `SELECT` statements are accepted, with blocked keywords and a 500-row cap.
- If a query fails, the error goes back to the model once for a corrected query.

### A real issue the tests caught

On the first real backfill, `assert_no_missing_demand_hours` failed the build with 47 missing hours. Investigation showed the pipeline was fine: EIA returns **null PJM demand values for about a day around two daylight-saving changes** (Nov 5, 2023 and Mar 10, 2024). Those ranges are now recorded, with the reason, in the `known_demand_gaps` dbt seed. The test ignores them but still fails on any new gap, so bad data never reaches the dashboard without anyone noticing.

## Data sources and licenses

| Source | What's used | License and terms | Attribution |
|---|---|---|---|
| [U.S. Energy Information Administration](https://www.eia.gov/opendata/), Hourly Electric Grid Monitor (EIA-930) | Hourly PJM demand | Public domain: U.S. government data, [free to reuse](https://www.eia.gov/about/copyrights_reuse.php) | "Source: U.S. Energy Information Administration (Oct 2026)" |
| [Open-Meteo.com](https://open-meteo.com/) historical weather API | Hourly temperature for Philadelphia, Newark and Washington DC | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The free API is for [non-commercial use only](https://open-meteo.com/en/terms) | "Weather data by Open-Meteo.com". **Modified:** averaged across the 3 cities and converted from °C to °F |

This is a non-commercial portfolio project, with no ads or subscriptions. The committed file `data/exports/fct_hourly_demand.parquet` contains data derived from both sources under the terms above. The same attribution appears in the dashboard footer.

## How to run it

Prerequisites: Docker Desktop (4GB+ RAM) and a free [EIA API key](https://www.eia.gov/opendata/).

```bash
cp .env.example .env                  # then set EIA_API_KEY, GROQ_API_KEY, and AIRFLOW_UID (output of `id -u`)
docker compose up airflow-init
docker compose up -d --build
```

Open http://localhost:8080 (user `airflow` / password `airflow`), unpause `grid_demand_pipeline` and trigger it. The first run backfills 3 years.

Dashboard:

```bash
pip install -r dashboard/requirements.txt
streamlit run dashboard/app.py
```

## Deploy the dashboard (Streamlit Community Cloud, free)

1. Sign in at [share.streamlit.io](https://share.streamlit.io) with GitHub. Click **Create app**, then **Deploy a public app from GitHub**.
2. Repository `Rupkatha422/grid-demand-pipeline`, branch `main`, main file `dashboard/app.py`.
3. **Advanced settings:** Python **3.11**. Under **Secrets**, add:
   ```toml
   GROQ_API_KEY = "your_groq_key"
   ```
4. Deploy. The app reads `data/exports/` from the repo. To refresh it, run the Airflow DAG locally, then commit and push `data/exports/`.

For local runs, keys go in `.env`, or in `.streamlit/secrets.toml`. Both are git-ignored.

## Repository layout

```
dags/grid_demand_dag.py     Airflow DAG
dags/include/               extract, load and config code
dbt/                        dbt project (models, tests, macros)
dashboard/app.py            Streamlit app
dashboard/assistant.py      'Ask the grid' text-to-SQL assistant
dags/include/briefing.py    AI daily briefing
dags/include/llm.py         Groq client
data/raw/                   raw API responses (git-ignored)
data/warehouse.duckdb       DuckDB warehouse (git-ignored)
data/exports/               Parquet export of the mart (committed, for Streamlit Cloud)
```
