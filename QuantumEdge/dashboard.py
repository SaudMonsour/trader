"""Streamlit dashboard for QuantumEdge."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

from config import get_settings
from logging_utils import configure_logging
from portfolio_tracker import PortfolioTracker

logger = configure_logging()


def load_table(db_path: Path, query: str) -> pd.DataFrame:
    """Load a SQLite query into a DataFrame, returning empty data on failure."""
    try:
        with sqlite3.connect(db_path) as conn:
            return pd.read_sql_query(query, conn)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Dashboard query failed: %s", exc)
        return pd.DataFrame()


def update_settings_state() -> None:
    """Persist dashboard-only settings in Streamlit session state."""
    st.session_state["risk_pct"] = st.session_state.get("risk_pct", 2.0)
    st.session_state["watchlist"] = st.session_state.get("watchlist", "SPY,QQQ,AAPL,TSLA,NVDA,AMD,MSFT")


def main() -> None:
    """Render the dark-themed QuantumEdge dashboard."""
    st.set_page_config(page_title="QuantumEdge", layout="wide", page_icon="⚛️")
    st.markdown("""
        <style>
        .stApp { background: #0e1117; color: #f5f5f5; }
        div[data-testid="stMetricValue"] { font-size: 2rem; }
        </style>
    """, unsafe_allow_html=True)
    settings = get_settings()
    tracker = PortfolioTracker(settings)
    update_settings_state()

    st.title("⚛️ QuantumEdge AI Trading Agent")
    mode_label = "🔴 LIVE REAL-MONEY TRADING" if settings.is_real_money_enabled() else "🟢 PAPER TRADING / TEST MODE"
    st.caption(f"Current broker mode: {mode_label}. Paper mode is safe testing; live mode sends real Alpaca orders.")
    if settings.is_real_money_enabled():
        st.error("LIVE MODE IS ENABLED: bot orders can use real money.")

    c1, c2, c3 = st.columns(3)
    if c1.button("▶️ Start Bot"):
        from main import QuantumEdgeBot

        try:
            bot = st.session_state.get("bot")
            if bot is None or not getattr(bot, "running", False):
                bot = QuantumEdgeBot()
                bot.start()
                st.session_state["bot"] = bot
            st.session_state["bot_status"] = "running"
            st.success("Bot service started in this Streamlit process.")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Dashboard failed to start bot: %s", exc)
            st.error(f"Bot failed to start: {exc}")
    if c2.button("⏹️ Stop Bot"):
        bot = st.session_state.get("bot")
        if bot is not None:
            bot.stop()
        st.session_state["bot_status"] = "stopped"
    if c3.button("🚨 Close All Positions"):
        bot = st.session_state.get("bot")
        if bot is not None:
            bot.execution.close_all_positions()
            st.warning("Close-all request sent to Alpaca.")
        else:
            st.warning("No dashboard bot is running. Start the bot first or run main.py to execute liquidation.")

    equity = tracker.equity_curve()
    latest_equity = float(equity["equity"].iloc[-1]) if not equity.empty else 0.0
    start_equity = float(equity["equity"].iloc[0]) if not equity.empty else latest_equity
    pnl = latest_equity - start_equity
    pnl_pct = (pnl / start_equity * 100) if start_equity else 0.0

    m1, m2, m3 = st.columns(3)
    m1.metric("Portfolio Value", f"${latest_equity:,.2f}")
    m2.metric("Today's PnL", f"${pnl:,.2f}", f"{pnl_pct:.2f}%")
    m3.metric("Bot Status", st.session_state.get("bot_status", "stopped").upper())

    st.subheader("Equity Curve")
    if not equity.empty:
        st.line_chart(equity.set_index("timestamp")["equity"])
    else:
        st.info("No equity data yet. Start the bot to populate performance history.")

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Recent Trades")
        st.dataframe(tracker.recent_trades(), use_container_width=True)
    with col_b:
        st.subheader("Recent Orders")
        st.dataframe(load_table(settings.database_path, "SELECT * FROM orders ORDER BY timestamp DESC LIMIT 50"), use_container_width=True)

    st.subheader("Risk Status")
    metrics = tracker.calculate_metrics()
    r1, r2, r3 = st.columns(3)
    r1.metric("Win Rate", f"{metrics['win_rate'] * 100:.1f}%")
    r2.metric("Sharpe", f"{metrics['sharpe']:.2f}")
    r3.metric("Max Drawdown", f"{metrics['max_drawdown'] * 100:.2f}%")

    with st.sidebar:
        st.header("Settings")
        st.slider("Max Daily Loss %", min_value=0.5, max_value=10.0, value=2.0, key="risk_pct")
        st.text_area("Watchlist", value=",".join(settings.watchlist), key="watchlist")
        st.write("Mode:", "🔴 LIVE REAL MONEY" if settings.is_real_money_enabled() else "🟢 PAPER TEST")
        st.write("Bracket Orders:", "enabled" if settings.use_bracket_orders else "disabled")


if __name__ == "__main__":
    main()
