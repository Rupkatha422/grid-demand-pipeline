"""'Ask the grid': natural-language questions -> SQL (LLM via Groq) -> DuckDB -> plain-English answer.

Guardrails:
- Queries run against an in-memory copy of the mart, with DuckDB file/network access disabled and
  the configuration locked, so generated SQL cannot read or write anything else.
- Only a single SELECT/WITH statement is accepted, and results are capped.
- If the SQL fails, the error goes back to the model once for a corrected query.
"""
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dags"))
from include import llm  # noqa: E402

MAX_ROWS = 500

SCHEMA = """Table: hourly  (one row per hour of PJM grid demand; times in US Eastern unless noted)
  hour_utc             TIMESTAMP  hour start in UTC
  hour_local           TIMESTAMP  hour start in US Eastern time
  date_local           DATE       Eastern calendar date
  hour_of_day          INTEGER    0-23, Eastern
  year                 INTEGER
  month                INTEGER    1-12
  month_name           VARCHAR    'January'...'December'
  day_name             VARCHAR    'Monday'...'Sunday'
  is_weekend           BOOLEAN
  season               VARCHAR    'Winter' (Dec-Feb), 'Spring', 'Summer' (Jun-Aug), 'Fall'
  demand_mwh           DOUBLE     electricity demand in that hour, MWh
  avg_temperature_f    DOUBLE     avg temperature across Philadelphia, Newark, Washington DC (°F); NULL for the newest few days
  cooling_degree_hours DOUBLE     max(temp - 65, 0)
  heating_degree_hours DOUBLE     max(65 - temp, 0)"""

SQL_PROMPT = f"""You translate questions about US electricity demand on the PJM grid into DuckDB SQL.

{SCHEMA}

Data covers {{start}} to {{end}}.

Rules:
- Write ONE read-only DuckDB SELECT (CTEs allowed) against the table `hourly` only.
- Aggregate when the question is about days, months or seasons; never return more than {MAX_ROWS} rows.
- Give columns readable snake_case aliases and round numbers sensibly.
- For "daily peak" use max(demand_mwh) per date_local.
- When returning times, use hour_local (US Eastern), not hour_utc, and say "Eastern" in aliases if helpful.
- If the question cannot be answered from this table, set "sql" to null and explain why in "explanation".
- Suggest a chart only when it helps: "line" for time series, "bar" for categories, "scatter" for two measures, else "none".

Return JSON only:
{{{{"sql": "...", "chart": {{{{"type": "line|bar|scatter|none", "x": "<column>", "y": "<column>"}}}}, "explanation": "<one sentence on the approach>"}}}}"""

ANSWER_PROMPT = """You answer questions about PJM grid electricity demand using ONLY the query result provided.
Be concise: 1-3 sentences, no lists or tables (the user can see the full result below your answer).
For many rows, summarize the highest, lowest and overall pattern instead of listing every value.
Round MWh to whole numbers with thousands separators and temperatures to 1 decimal; include units.
Show times in US Eastern. Do not speculate beyond the data. If the result is empty, say so plainly."""

BLOCKED = re.compile(r"\b(insert|update|delete|drop|create|alter|attach|detach|copy|export|import|install|load|"
                     r"pragma|set|call|read_csv\w*|read_parquet|read_json\w*|read_text|glob|httpfs)\b", re.I)


@dataclass
class Answer:
    question: str
    text: str = ""
    sql: str | None = None
    explanation: str = ""
    chart: dict = field(default_factory=dict)
    data: pd.DataFrame | None = None
    error: str | None = None


def connect(parquet_path: Path) -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB holding the mart, then locked down so queries can't touch files or the network."""
    con = duckdb.connect(":memory:")
    con.execute(f"""
        create table hourly as
        select hour_utc, hour_local, date_local,
               hour_of_day_local::integer       as hour_of_day,
               year(date_local)::integer        as year,
               month(date_local)::integer       as month,
               monthname(date_local)            as month_name,
               dayname(date_local)              as day_name,
               isodow(date_local) in (6, 7)     as is_weekend,
               case when month(date_local) in (12, 1, 2) then 'Winter'
                    when month(date_local) in (3, 4, 5) then 'Spring'
                    when month(date_local) in (6, 7, 8) then 'Summer' else 'Fall' end as season,
               demand_mwh, avg_temperature_f, cooling_degree_hours, heating_degree_hours
        from read_parquet('{parquet_path}')
    """)
    con.execute("set enable_external_access = false")
    con.execute("set lock_configuration = true")
    return con


def validate(sql: str) -> str:
    """Accept exactly one SELECT/WITH statement with no blocked keywords."""
    sql = sql.strip().rstrip(";").strip()
    if ";" in sql:
        raise ValueError("Only a single statement is allowed.")
    if not re.match(r"^(select|with)\b", sql, re.I):
        raise ValueError("Only SELECT queries are allowed.")
    if m := BLOCKED.search(sql):
        raise ValueError(f"Keyword not allowed: {m.group(0)}")
    return sql


def _run(con, sql: str) -> pd.DataFrame:
    sql = validate(sql)
    return con.execute(f"select * from ({sql}) limit {MAX_ROWS}").df()


def extremes(df: pd.DataFrame) -> str:
    """Highest/lowest row per numeric column, computed in code so the model doesn't misread the table."""
    if len(df) < 3:
        return ""
    lines = ["Verified extremes (trust these over your own reading of the table):"]
    for col in df.select_dtypes("number").columns:
        hi, lo = df.loc[df[col].idxmax()], df.loc[df[col].idxmin()]
        lines.append(f"- {col}: highest {hi[col]:,.1f} ({hi.drop(col).to_dict()}), "
                     f"lowest {lo[col]:,.1f} ({lo.drop(col).to_dict()})")
    return "\n".join(lines)


def ask(con: duckdb.DuckDBPyConnection, question: str, history: list[dict] | None = None) -> Answer:
    """Answer one question. `history` holds earlier (question, sql) pairs for follow-ups."""
    out = Answer(question=question)
    start, end = con.execute("select min(date_local), max(date_local) from hourly").fetchone()
    messages = [{"role": "system", "content": SQL_PROMPT.format(start=start, end=end)}]
    for turn in (history or [])[-4:]:
        messages += [{"role": "user", "content": turn["question"]},
                     {"role": "assistant", "content": json.dumps({"sql": turn.get("sql")})}]
    messages.append({"role": "user", "content": question})

    try:
        plan = llm.chat_json(messages, temperature=0)
        out.sql, out.explanation = plan.get("sql"), plan.get("explanation", "")
        out.chart = plan.get("chart") or {}
        if not out.sql:
            out.text = out.explanation or "I can't answer that from the grid data."
            return out
        try:
            out.data = _run(con, out.sql)
        except Exception as first_error:  # one self-correction attempt
            messages += [{"role": "assistant", "content": json.dumps(plan)},
                         {"role": "user", "content": f"That query failed: {first_error}. Return corrected JSON."}]
            plan = llm.chat_json(messages, temperature=0)
            out.sql, out.chart = plan.get("sql"), plan.get("chart") or {}
            out.data = _run(con, out.sql)

        preview = out.data.head(50).to_csv(index=False)
        out.text = llm.chat([
            {"role": "system", "content": ANSWER_PROMPT},
            {"role": "user", "content": f"Question: {question}\n\nQuery result ({len(out.data)} rows, CSV):\n{preview}"
                                        f"\n{extremes(out.data)}"},
        ], temperature=0.2, max_tokens=300)
    except Exception as e:
        out.error = str(e)
    return out
