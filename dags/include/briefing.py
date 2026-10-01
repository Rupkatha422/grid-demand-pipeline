"""AI daily briefing: compute the day's facts in SQL, then have an LLM (via Groq) write them up.

The model only phrases numbers we computed; it is told not to introduce any of its own.
"""
import json
import logging
from datetime import datetime, timezone

import duckdb

from include import config, llm

log = logging.getLogger(__name__)
BRIEFING_PATH = config.EXPORT_DIR / "briefing.json"

FACTS_SQL = """
with days as (
    select date_local,
           count(*)                 as hours,
           max(demand_mwh)          as peak_mwh,
           avg(demand_mwh)          as avg_mwh,
           avg(avg_temperature_f)   as avg_temp_f,
           max(avg_temperature_f)   as max_temp_f,
           arg_max(hour_local, demand_mwh) as peak_hour_local,
           arg_max(avg_temperature_f, demand_mwh) as temp_at_peak_f
    from fct_hourly_demand
    group by date_local
),
-- Latest day with a full day of demand (23-25 hours allows for daylight-saving days).
target as (
    select * from days where hours >= 23 order by date_local desc limit 1
)
select
    t.date_local,
    dayname(t.date_local)                           as day_name,
    round(t.peak_mwh)                               as peak_mwh,
    strftime(t.peak_hour_local, '%-I %p')           as peak_hour,
    round(t.temp_at_peak_f, 1)                      as temp_at_peak_f,
    round(t.avg_mwh)                                as avg_mwh,
    round(t.max_temp_f, 1)                          as max_temp_f,
    -- vs. the same weekday over the previous 4 weeks
    round(100 * (t.avg_mwh / (select avg(avg_mwh) from days d
        where d.date_local in (t.date_local - 7, t.date_local - 14, t.date_local - 21, t.date_local - 28)) - 1), 1)
                                                    as pct_vs_same_weekday_4wk,
    -- last 7 days vs. the 7 days before
    round(100 * ((select avg(avg_mwh) from days d where d.date_local between t.date_local - 6 and t.date_local)
        / (select avg(avg_mwh) from days d where d.date_local between t.date_local - 13 and t.date_local - 7) - 1), 1)
                                                    as pct_7day_vs_prior_7day,
    -- vs. the typical peak on days with a similar average temperature (±3°F)
    round(100 * (t.peak_mwh / (select avg(peak_mwh) from days d
        where d.date_local < t.date_local and abs(d.avg_temp_f - t.avg_temp_f) <= 3) - 1), 1)
                                                    as pct_vs_similar_temp_days,
    -- rank of this day's peak within the past 365 days (1 = highest)
    (select count(*) + 1 from days d
        where d.date_local between t.date_local - 365 and t.date_local - 1 and d.peak_mwh > t.peak_mwh)
                                                    as peak_rank_365d,
    (select count(*) from days d where d.date_local between t.date_local - 365 and t.date_local - 1)
                                                    as days_in_rank_window
from target t
"""

SYSTEM_PROMPT = """You are an energy analyst writing a short daily briefing about electricity demand on the
PJM grid (13 US states including New Jersey) for a public dashboard.

Rules:
- Use ONLY the numbers in the JSON facts. Never invent, estimate or round to new values.
- If a fact is null, don't mention it.
- Demand values are in MWh per hour; write them with thousands separators (e.g. 132,400 MWh).
- Percentages: say "above"/"below" rather than using a minus sign.
- Plain, confident, no hype, no emojis. Never give advice.

Return JSON: {"headline": "<max 12 words>", "summary": "<2-4 sentences>"}"""


def compute_facts() -> dict:
    with duckdb.connect(str(config.WAREHOUSE_PATH), read_only=True) as con:
        cur = con.execute(FACTS_SQL)
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("No complete day of demand data in fct_hourly_demand yet.")
        facts = dict(zip([c[0] for c in cur.description], row))
    facts["date_local"] = facts["date_local"].isoformat()
    return facts


def write_briefing() -> str:
    """Generate the briefing for the latest complete day and save it next to the dashboard export."""
    facts = compute_facts()
    log.info("Briefing facts: %s", facts)
    result = llm.chat_json([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "Facts:\n" + json.dumps(facts, default=str)},
    ], temperature=0.3, max_tokens=400)

    briefing = {
        "date": facts["date_local"],
        "headline": result.get("headline", "").strip(),
        "summary": result.get("summary", "").strip(),
        "facts": facts,
        "model": llm.model(),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    config.EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    BRIEFING_PATH.write_text(json.dumps(briefing, indent=2, default=str))
    log.info("Wrote %s: %s", BRIEFING_PATH, briefing["headline"])
    return str(BRIEFING_PATH)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(compute_facts(), indent=2, default=str))
