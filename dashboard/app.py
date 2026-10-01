"""PJM demand vs. temperature dashboard. Run: streamlit run dashboard/app.py"""
import html
import json
import os
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import assistant

DATA = Path(os.getenv("DASHBOARD_DATA",
                      Path(__file__).resolve().parents[1] / "data" / "exports" / "fct_hourly_demand.parquet"))

# Palette: one blue for single-series charts, a fixed categorical order for seasons,
# a single-hue ramp for magnitude. A season keeps its color even when filtered out.
BLUE, BLUE_DARK = "#2a78d6", "#104281"
INK, INK_MUTED = "#14161a", "#6b6a66"
SEASONS = ["Winter", "Spring", "Summer", "Fall"]
SEASON_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
SEQUENTIAL = ["#e6f0fc", "#9ec5f4", "#5598e7", "#256abf", "#0d366b"]
SEASON_BY_MONTH = {12: "Winter", 1: "Winter", 2: "Winter", 3: "Spring", 4: "Spring", 5: "Spring",
                   6: "Summer", 7: "Summer", 8: "Summer", 9: "Fall", 10: "Fall", 11: "Fall"}

st.set_page_config(page_title="PJM Grid Demand", page_icon="⚡", layout="wide")

st.markdown(f"""
<style>
  .block-container {{ padding-top: 3.5rem; max-width: 1280px; }}
  .hero {{
    background: linear-gradient(135deg, #0d366b 0%, #1c5cab 60%, #2a78d6 100%);
    color: #fff; border-radius: 16px; padding: 28px 32px; margin-bottom: 20px;
  }}
  .hero .eyebrow {{ font-size: .78rem; letter-spacing: .12em; text-transform: uppercase; opacity: .75; }}
  .hero h1 {{ color: #fff; font-size: 2.1rem; line-height: 1.2; margin: 6px 0 10px; padding: 0; }}
  .hero p {{ margin: 0; opacity: .88; max-width: 760px; font-size: 1rem; }}
  .hero .answer {{
    display: inline-block; margin-top: 16px; padding: 8px 14px; border-radius: 999px;
    background: rgba(255,255,255,.14); font-weight: 600;
  }}
  .card {{
    background: #fff; border: 1px solid #e7e8eb; border-radius: 12px; padding: 16px 18px; height: 100%;
  }}
  .card .label {{ color: {INK_MUTED}; font-size: .82rem; margin-bottom: 6px; }}
  .card .value {{ color: {INK}; font-size: 1.65rem; font-weight: 700; line-height: 1.15; }}
  .card .sub {{ color: {INK_MUTED}; font-size: .8rem; margin-top: 4px; }}
  .card .up {{ color: #b8431a; font-weight: 600; }}
  .card .down {{ color: #1c5cab; font-weight: 600; }}
  div[data-testid="stTabs"] button p {{ font-size: .95rem; font-weight: 600; }}
  .note {{ color: {INK_MUTED}; font-size: .85rem; margin: -4px 0 8px; }}
  .brief {{
    background: #fff; border: 1px solid #e7e8eb; border-left: 4px solid {BLUE}; border-radius: 12px;
    padding: 16px 20px; margin: 16px 0 4px;
  }}
  .brief .tag {{
    display: inline-block; font-size: .72rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase;
    color: {BLUE_DARK}; background: #e6f0fc; border-radius: 999px; padding: 3px 10px; margin-right: 8px;
  }}
  .brief .date {{ color: {INK_MUTED}; font-size: .8rem; }}
  .brief h3 {{ font-size: 1.15rem; margin: 10px 0 6px; padding: 0; color: {INK}; }}
  .brief p {{ margin: 0; color: #2d3036; line-height: 1.55; }}
  .brief .meta {{ color: {INK_MUTED}; font-size: .75rem; margin-top: 10px; }}
  .footer {{ color: {INK_MUTED}; font-size: .8rem; margin-top: 28px; border-top: 1px solid #e7e8eb; padding-top: 12px; }}
</style>
""", unsafe_allow_html=True)


def chart_style(chart: alt.Chart, height: int = 320) -> alt.Chart:
    """Recessive axes and gridlines so the data carries the visual weight."""
    return (chart.properties(height=height)
            .configure_view(strokeWidth=0)
            .configure_axis(grid=True, gridColor="#eceef1", domain=False, tickColor="#e7e8eb",
                            labelColor=INK_MUTED, titleColor=INK_MUTED, labelFontSize=11,
                            titleFontSize=11, titleFontWeight="normal", labelPadding=6)
            .configure_legend(labelColor=INK, titleColor=INK_MUTED, orient="top", title=None,
                              symbolStrokeWidth=3, labelFontSize=12))


def card(label: str, value: str, sub: str = "") -> str:
    return f'<div class="card"><div class="label">{label}</div><div class="value">{value}</div>' \
           f'<div class="sub">{sub}</div></div>'


@st.cache_data
def load(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    df["date_local"] = pd.to_datetime(df["date_local"])
    df["hour_local"] = pd.to_datetime(df["hour_local"])
    df["month"] = df["date_local"].dt.month
    df["season"] = df["month"].map(SEASON_BY_MONTH)
    return df


def slope(x: pd.Series, y: pd.Series) -> float:
    """MWh change per 1°F, from a straight-line fit. NaN if there's too little data."""
    return float(np.polyfit(x, y, 1)[0]) if len(x) >= 24 and x.nunique() > 1 else float("nan")


if not DATA.exists():
    st.error(f"No data yet at {DATA}. Run the Airflow DAG first.")
    st.stop()

df = load(DATA)

# ---------- Filters (one row, above everything they affect) ----------
lo, hi = df["date_local"].min().date(), df["date_local"].max().date()
f1, f2 = st.columns([3, 2])
with f1:
    start, end = st.slider("Date range", min_value=lo, max_value=hi, value=(lo, hi), format="MMM D, YYYY")
with f2:
    seasons = st.multiselect("Seasons", SEASONS, default=SEASONS)
view = df[(df["date_local"].dt.date.between(start, end)) & df["season"].isin(seasons)]
if view.empty:
    st.warning("No data for these filters.")
    st.stop()
with_temp = view.dropna(subset=["avg_temperature_f"])

# ---------- Headline numbers ----------
hot = with_temp[with_temp["avg_temperature_f"] > 65]
cold = with_temp[with_temp["avg_temperature_f"] < 50]
cooling_slope = slope(hot["avg_temperature_f"], hot["demand_mwh"])
heating_slope = slope(cold["avg_temperature_f"], cold["demand_mwh"])
peak = view.loc[view["demand_mwh"].idxmax()]
mild_avg = with_temp[with_temp["avg_temperature_f"].between(60, 70)]["demand_mwh"].mean()
hot_avg = with_temp[with_temp["avg_temperature_f"] >= 85]["demand_mwh"].mean()

answer = (f"Above 65°F, every extra 1°F adds about <b>{cooling_slope:,.0f} MWh</b> per hour"
          if np.isfinite(cooling_slope) else "Not enough warm hours in this range to measure the heat effect")
st.markdown(f"""
<div class="hero">
  <div class="eyebrow">⚡ PJM Interconnection · hourly demand vs. temperature</div>
  <h1>How much does heat drive power demand?</h1>
  <p>Hourly electricity demand for the PJM grid (13 states incl. New Jersey) from the U.S. EIA, joined to the
     average temperature across Philadelphia, Newark and Washington DC.</p>
  <div class="answer">{answer}</div>
</div>
""", unsafe_allow_html=True)

k1, k2, k3, k4 = st.columns(4)
k1.markdown(card("Peak hourly demand", f"{peak['demand_mwh']:,.0f} MWh",
                 f"{peak['hour_local']:%b %-d, %Y · %-I %p}"), unsafe_allow_html=True)
k2.markdown(card("Average hourly demand", f"{view['demand_mwh'].mean():,.0f} MWh",
                 f"{len(view):,} hours · {view['date_local'].nunique():,} days"), unsafe_allow_html=True)
if np.isfinite(hot_avg) and np.isfinite(mild_avg):
    diff = hot_avg / mild_avg - 1
    cls = "up" if diff >= 0 else "down"
    k3.markdown(card("Hot hours (≥85°F) vs. mild (60–70°F)", f'<span class="{cls}">{diff:+.0%}</span>',
                     f"{hot_avg:,.0f} vs. {mild_avg:,.0f} MWh"), unsafe_allow_html=True)
else:
    k3.markdown(card("Hot hours (≥85°F) vs. mild (60–70°F)", "—", "Not enough hot or mild hours"),
                unsafe_allow_html=True)
k4.markdown(card("Cold effect (below 50°F)",
                 f"{-heating_slope:+,.0f} MWh" if np.isfinite(heating_slope) else "—",
                 "per 1°F colder (electric heating)" if np.isfinite(heating_slope) else "Not enough cold hours"),
            unsafe_allow_html=True)

# ---------- AI daily briefing (written by the Airflow DAG) ----------
BRIEFING = DATA.parent / "briefing.json"
if BRIEFING.exists():
    b = json.loads(BRIEFING.read_text())
    day = pd.Timestamp(b["date"])
    st.markdown(f"""
    <div class="brief">
      <span class="tag">✨ AI daily briefing</span><span class="date">{day:%A, %B %-d, %Y}</span>
      <h3>{html.escape(b['headline'])}</h3>
      <p>{html.escape(b['summary'])}</p>
      <div class="meta">Written by {html.escape(b['model'])} (via Groq) from figures computed in SQL. Generated {b['generated_at'][:16].replace('T', ' ')} UTC.</div>
    </div>
    """, unsafe_allow_html=True)

st.write("")
tab_trend, tab_ask, tab_weather, tab_patterns, tab_data = st.tabs(
    ["📈 Demand trend", "🤖 Ask the grid", "🌡️ Weather effect", "🕒 Daily & seasonal patterns", "🗂️ Data"])

# ---------- Tab 1: demand over time ----------
with tab_trend:
    daily = view.groupby("date_local", as_index=False).agg(
        peak_mwh=("demand_mwh", "max"), avg_mwh=("demand_mwh", "mean"), avg_temp_f=("avg_temperature_f", "mean"))
    st.markdown("**Daily peak demand**")
    st.markdown('<div class="note">Hover for the day\'s peak, average and temperature. Drag to pan, scroll to zoom.</div>',
                unsafe_allow_html=True)
    base = alt.Chart(daily).encode(x=alt.X("date_local:T", title=None))
    hover = alt.selection_point(fields=["date_local"], nearest=True, on="pointerover", empty=False)
    area = base.mark_area(color=BLUE, opacity=0.10).encode(y=alt.Y("peak_mwh:Q", title="MWh",
                                                                    scale=alt.Scale(zero=False)))
    line = base.mark_line(color=BLUE, strokeWidth=2).encode(y="peak_mwh:Q")
    points = base.mark_point(size=60, filled=True, color=BLUE, stroke="white", strokeWidth=2).encode(
        y="peak_mwh:Q", opacity=alt.condition(hover, alt.value(1), alt.value(0)),
        tooltip=[alt.Tooltip("date_local:T", title="Date", format="%a %b %-d, %Y"),
                 alt.Tooltip("peak_mwh:Q", title="Peak MWh", format=",.0f"),
                 alt.Tooltip("avg_mwh:Q", title="Average MWh", format=",.0f"),
                 alt.Tooltip("avg_temp_f:Q", title="Avg °F", format=".1f")]).add_params(hover)
    rule = base.mark_rule(color="#c9ccd1").encode(opacity=alt.condition(hover, alt.value(1), alt.value(0)))
    st.altair_chart(chart_style((area + line + rule + points).interactive(bind_y=False), 360), width="stretch")

# ---------- Tab: Ask the grid (LLM text-to-SQL) ----------
@st.cache_resource
def grid_db(path: str):
    return assistant.connect(Path(path))


def groq_key() -> str:
    try:  # Streamlit Community Cloud stores keys in st.secrets
        if "GROQ_API_KEY" in st.secrets:
            return st.secrets["GROQ_API_KEY"]
    except Exception:
        pass
    return assistant.llm.api_key()


def answer_chart(ans: assistant.Answer):
    spec, data = ans.chart or {}, ans.data
    kind, x, y = spec.get("type"), spec.get("x"), spec.get("y")
    if data is None or data.empty or kind not in ("line", "bar", "scatter") or x not in data or y not in data:
        return None
    is_num = pd.api.types.is_numeric_dtype(data[x])
    few_whole_numbers = is_num and data[x].nunique() <= 31 and (data[x] % 1 == 0).all()  # months, hours, years
    if pd.api.types.is_datetime64_any_dtype(data[x]) or "date" in x:
        x_type = "T"
    elif kind == "bar" or few_whole_numbers or not is_num:
        x_type = "O"
    else:
        x_type = "Q"
    mark = {"line": alt.Chart(data).mark_line(color=BLUE, strokeWidth=2, point=len(data) <= 60),
            "bar": alt.Chart(data).mark_bar(color=BLUE, cornerRadiusTopLeft=4, cornerRadiusTopRight=4),
            "scatter": alt.Chart(data).mark_circle(color=BLUE, size=40, opacity=0.6)}[kind]
    return chart_style(mark.encode(
        x=alt.X(f"{x}:{x_type}", title=x.replace("_", " "), sort=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y(f"{y}:Q", title=y.replace("_", " "), scale=alt.Scale(zero=kind == "bar")),
        tooltip=list(data.columns[:6])), 300)


def show_answer(ans: assistant.Answer):
    with st.chat_message("user"):
        st.write(ans.question)
    with st.chat_message("assistant", avatar="⚡"):
        if ans.error:
            st.error(f"Sorry, I couldn't answer that: {ans.error}")
            return
        st.markdown(ans.text)
        if (chart := answer_chart(ans)) is not None:
            st.altair_chart(chart, width="stretch")
        if ans.sql:
            with st.expander("How I got this: SQL and data"):
                if ans.explanation:
                    st.caption(ans.explanation)
                st.code(ans.sql, language="sql")
                if ans.data is not None:
                    st.dataframe(ans.data, width="stretch", hide_index=True)


EXAMPLES = ["What was the highest demand hour ever, and how hot was it?",
            "Average daily peak demand by month",
            "Which day of the week uses the most power in summer?",
            "How does demand on days above 90°F compare to days below 70°F?"]

with tab_ask:
    st.markdown("**Ask the grid**")
    st.markdown('<div class="note">Ask a question in plain English. An open-weight LLM (gpt-oss-120b via Groq) writes SQL, '
                'runs it on a locked-down, read-only copy of the data, and explains the result. Always check '
                'the SQL under each answer.</div>', unsafe_allow_html=True)
    key = groq_key()
    if not key:
        st.info("Add `GROQ_API_KEY` to `.env` (or Streamlit secrets) to enable the assistant.")
    else:
        os.environ.setdefault("GROQ_API_KEY", key)
        st.session_state.setdefault("chat", [])
        cols = st.columns(len(EXAMPLES))
        clicked = next((q for c, q in zip(cols, EXAMPLES) if c.button(q, width="stretch")), None)
        typed = st.chat_input("e.g. What was the peak demand last July?")
        question = typed or clicked
        for past in st.session_state["chat"]:
            show_answer(past)
        if question:
            with st.spinner("Thinking…"):
                history = [{"question": a.question, "sql": a.sql} for a in st.session_state["chat"]]
                ans = assistant.ask(grid_db(str(DATA)).cursor(), question, history)
            st.session_state["chat"].append(ans)
            show_answer(ans)
        if st.session_state["chat"] and st.button("Clear conversation"):
            st.session_state["chat"] = []
            st.rerun()

# ---------- Tab 2: temperature vs. demand ----------
with tab_weather:
    left, right = st.columns([3, 2])
    with left:
        st.markdown("**Temperature vs. hourly demand**")
        st.markdown('<div class="note">Each dot is one hour. The line is the average demand at each temperature: '
                    'demand rises on both the cold side (heating) and the hot side (cooling).</div>',
                    unsafe_allow_html=True)
        sample = with_temp.sample(min(len(with_temp), 5000), random_state=0)  # keeps the browser responsive
        dots = alt.Chart(sample).mark_circle(size=14, opacity=0.25, color=BLUE).encode(
            x=alt.X("avg_temperature_f:Q", title="Average temperature (°F)", scale=alt.Scale(zero=False)),
            y=alt.Y("demand_mwh:Q", title="Hourly demand (MWh)", scale=alt.Scale(zero=False)),
            tooltip=[alt.Tooltip("hour_local:T", title="Hour", format="%b %-d %Y, %-I %p"),
                     alt.Tooltip("avg_temperature_f:Q", title="°F", format=".1f"),
                     alt.Tooltip("demand_mwh:Q", title="MWh", format=",.0f")])
        binned = (with_temp.assign(temp_bin=with_temp["avg_temperature_f"].round())
                  .groupby("temp_bin", as_index=False)["demand_mwh"].mean())
        trend = alt.Chart(binned).transform_loess("temp_bin", "demand_mwh", bandwidth=0.4).mark_line(
            color=BLUE_DARK, strokeWidth=3).encode(x="temp_bin:Q", y="demand_mwh:Q")
        st.altair_chart(chart_style(dots + trend, 380), width="stretch")
    with right:
        st.markdown("**Average demand by temperature band**")
        st.markdown('<div class="note">How much the grid works in each 10°F band.</div>', unsafe_allow_html=True)
        bands = with_temp.assign(band=(with_temp["avg_temperature_f"] // 10 * 10).astype(int))
        bands = bands.groupby("band", as_index=False).agg(avg_mwh=("demand_mwh", "mean"),
                                                          hours=("demand_mwh", "size"))
        bands["label"] = bands["band"].astype(str) + "–" + (bands["band"] + 9).astype(str) + "°F"
        bars = alt.Chart(bands).mark_bar(color=BLUE, cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
            x=alt.X("label:N", title=None, sort=alt.SortField("band"), axis=alt.Axis(labelAngle=0)),
            y=alt.Y("avg_mwh:Q", title="Average MWh"),
            tooltip=[alt.Tooltip("label:N", title="Band"), alt.Tooltip("avg_mwh:Q", title="Avg MWh", format=",.0f"),
                     alt.Tooltip("hours:Q", title="Hours", format=",")])
        st.altair_chart(chart_style(bars, 380), width="stretch")

# ---------- Tab 3: daily and seasonal patterns ----------
with tab_patterns:
    left, right = st.columns(2)
    with left:
        st.markdown("**Average demand by hour of day**")
        st.markdown('<div class="note">Summer peaks in the late afternoon (air conditioning); winter has '
                    'morning and evening peaks.</div>', unsafe_allow_html=True)
        profile = view.groupby(["season", "hour_of_day_local"], as_index=False)["demand_mwh"].mean()
        lines = alt.Chart(profile).mark_line(strokeWidth=2.5, point=alt.OverlayMarkDef(size=36, filled=True)).encode(
            x=alt.X("hour_of_day_local:O", title="Hour of day (Eastern)", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("demand_mwh:Q", title="Average MWh", scale=alt.Scale(zero=False)),
            color=alt.Color("season:N", scale=alt.Scale(domain=SEASONS, range=SEASON_COLORS)),
            tooltip=["season:N", alt.Tooltip("hour_of_day_local:O", title="Hour"),
                     alt.Tooltip("demand_mwh:Q", title="Avg MWh", format=",.0f")])
        st.altair_chart(chart_style(lines, 360), width="stretch")
    with right:
        st.markdown("**When the grid works hardest**")
        st.markdown('<div class="note">Average demand by month and hour. Darker means more demand.</div>',
                    unsafe_allow_html=True)
        heat = view.groupby(["month", "hour_of_day_local"], as_index=False)["demand_mwh"].mean()
        heat["month_name"] = pd.to_datetime(heat["month"], format="%m").dt.strftime("%b")
        month_order = [m for m in ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
                       if m in set(heat["month_name"])]
        grid = alt.Chart(heat).mark_rect(cornerRadius=2, stroke="white", strokeWidth=1).encode(
            x=alt.X("hour_of_day_local:O", title="Hour of day (Eastern)", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("month_name:N", title=None, sort=month_order),
            color=alt.Color("demand_mwh:Q", title="Avg MWh", scale=alt.Scale(range=SEQUENTIAL),
                            legend=alt.Legend(orient="right", format=",.0f", gradientLength=200)),
            tooltip=[alt.Tooltip("month_name:N", title="Month"), alt.Tooltip("hour_of_day_local:O", title="Hour"),
                     alt.Tooltip("demand_mwh:Q", title="Avg MWh", format=",.0f")])
        st.altair_chart(chart_style(grid, 360), width="stretch")

# ---------- Tab 4: raw table ----------
with tab_data:
    cols = ["hour_local", "demand_mwh", "avg_temperature_f", "cooling_degree_hours", "heating_degree_hours"]
    st.dataframe(
        view.sort_values("hour_utc", ascending=False)[cols], width="stretch", hide_index=True,
        column_config={
            "hour_local": st.column_config.DatetimeColumn("Hour (Eastern)", format="MMM D, YYYY h a"),
            "demand_mwh": st.column_config.NumberColumn("Demand (MWh)", format="%,.0f"),
            "avg_temperature_f": st.column_config.NumberColumn("Avg temp (°F)", format="%.1f"),
            "cooling_degree_hours": st.column_config.NumberColumn("Cooling degree-hours", format="%.1f"),
            "heating_degree_hours": st.column_config.NumberColumn("Heating degree-hours", format="%.1f"),
        })
    st.download_button("Download CSV", view[cols].to_csv(index=False), "pjm_hourly_demand.csv", "text/csv")

st.markdown(f"""
<div class="footer">
  Data: U.S. Energy Information Administration (EIA-930) · Open-Meteo historical weather.
  Built with Airflow, DuckDB, dbt and Streamlit. Last data point: {df['hour_local'].max():%b %-d, %Y %-I %p} Eastern.
</div>
""", unsafe_allow_html=True)
