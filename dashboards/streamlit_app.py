from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit_autorefresh import st_autorefresh


DB_PATH = Path(os.getenv("FREQTRADE_DB_PATH", "/app/experiments/database/results.sqlite"))

st.set_page_config(page_title="Freqtrade Lab", page_icon="FT", layout="wide")


def get_connection() -> sqlite3.Connection | None:
    if not DB_PATH.exists():
        return None
    return sqlite3.connect(DB_PATH)


def load_dataframe(query: str, params: tuple = ()) -> pd.DataFrame:
    connection = get_connection()
    if connection is None:
        return pd.DataFrame()
    try:
        return pd.read_sql_query(query, connection, params=params)
    finally:
        connection.close()


st_autorefresh(interval=5000, key="freqtrade_dashboard_refresh")

st.title("Freqtrade Strategy Benchmark")
st.caption("SQLite-backed live view of queued, running, completed and failed strategy runs.")

if not DB_PATH.exists():
    st.warning(f"Database not found yet: {DB_PATH}")
    st.stop()

status_df = load_dataframe(
    """
    SELECT status, COUNT(*) AS run_count
    FROM runs
    GROUP BY status
    ORDER BY status
    """
)

all_runs_df = load_dataframe(
    """
    SELECT
        runs.id,
        strategies.class_name AS strategy_name,
        strategies.source_folder,
        strategies.market_type,
        runs.status,
        runs.phase,
        runs.timerange,
        runs.status_message,
        runs.updated_at
    FROM runs
    JOIN strategies ON strategies.id = runs.strategy_id
    ORDER BY runs.updated_at DESC
    """
)

metrics_df = load_dataframe(
    """
    SELECT
        runs.id AS run_id,
        strategies.class_name AS strategy_name,
        strategies.source_folder,
        strategies.market_type,
        metrics.metric_scope,
        metrics.profit_total,
        metrics.profit_abs,
        metrics.drawdown,
        metrics.sharpe,
        metrics.sortino,
        metrics.winrate,
        metrics.profit_factor,
        metrics.trade_count,
        metrics.avg_trade_duration
    FROM metrics
    JOIN runs ON runs.id = metrics.run_id
    JOIN strategies ON strategies.id = runs.strategy_id
    ORDER BY runs.id DESC
    """
)

event_df = load_dataframe(
    """
    SELECT
        events.created_at,
        runs.id AS run_id,
        strategies.class_name AS strategy_name,
        events.event_type,
        events.message
    FROM events
    JOIN runs ON runs.id = events.run_id
    JOIN strategies ON strategies.id = runs.strategy_id
    ORDER BY events.created_at DESC
    LIMIT 200
    """
)

left, middle, right = st.columns(3)
with left:
    total_runs = int(status_df["run_count"].sum()) if not status_df.empty else 0
    st.metric("Runs", total_runs)
with middle:
    running_count = int(status_df.loc[status_df["status"] == "running", "run_count"].sum()) if not status_df.empty else 0
    st.metric("Running", running_count)
with right:
    failed_count = int(status_df.loc[status_df["status"] == "failed", "run_count"].sum()) if not status_df.empty else 0
    st.metric("Failed", failed_count)

st.subheader("Queue state")
if status_df.empty:
    st.info("No runs queued yet.")
else:
    st.dataframe(status_df, use_container_width=True, hide_index=True)

source_folder_options = sorted(all_runs_df["source_folder"].dropna().unique().tolist()) if not all_runs_df.empty else []
market_type_options = sorted(all_runs_df["market_type"].dropna().unique().tolist()) if not all_runs_df.empty else []

filters = st.columns(2)
with filters[0]:
    selected_sources = st.multiselect("Source folders", source_folder_options, default=source_folder_options)
with filters[1]:
    selected_markets = st.multiselect("Market types", market_type_options, default=market_type_options)

filtered_runs = all_runs_df.copy()
if not filtered_runs.empty:
    if selected_sources:
        filtered_runs = filtered_runs[filtered_runs["source_folder"].isin(selected_sources)]
    if selected_markets:
        filtered_runs = filtered_runs[filtered_runs["market_type"].isin(selected_markets)]

st.subheader("Runs")
if filtered_runs.empty:
    st.info("No runs match the current filters.")
else:
    st.dataframe(filtered_runs, use_container_width=True, hide_index=True)

filtered_metrics = metrics_df.copy()
if not filtered_metrics.empty:
    if selected_sources:
        filtered_metrics = filtered_metrics[filtered_metrics["source_folder"].isin(selected_sources)]
    if selected_markets:
        filtered_metrics = filtered_metrics[filtered_metrics["market_type"].isin(selected_markets)]

st.subheader("Metrics")
if filtered_metrics.empty:
    st.info("Metrics will appear here as soon as a backtest result is parsed.")
else:
    st.dataframe(filtered_metrics, use_container_width=True, hide_index=True)

    final_metrics = filtered_metrics[filtered_metrics["metric_scope"] == "final"]
    baseline_metrics = filtered_metrics[filtered_metrics["metric_scope"] == "baseline"]
    chart_source = final_metrics if not final_metrics.empty else baseline_metrics

    if not chart_source.empty and "profit_total" in chart_source:
        chart = px.bar(
            chart_source.sort_values("profit_total", ascending=False),
            x="strategy_name",
            y="profit_total",
            color="market_type",
            hover_data=["source_folder", "metric_scope", "trade_count", "sharpe", "drawdown"],
            title="Profit by strategy",
        )
        chart.update_layout(height=420)
        st.plotly_chart(chart, use_container_width=True)

st.subheader("Recent events")
if event_df.empty:
    st.info("No events yet.")
else:
    st.dataframe(event_df, use_container_width=True, hide_index=True)
