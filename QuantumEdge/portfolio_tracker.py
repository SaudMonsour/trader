"""Portfolio performance persistence and analytics."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from config import Settings
from logging_utils import configure_logging

logger = configure_logging()


class PortfolioTracker:
    """Track equity, trades, and performance reports in SQLite."""

    def __init__(self, settings: Settings) -> None:
        """Initialize database tables for performance tracking."""
        self.db_path = Path(settings.database_path)
        self._init_db()

    def _init_db(self) -> None:
        """Create required tracking tables when missing."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS equity_curve (timestamp TEXT PRIMARY KEY, equity REAL NOT NULL)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty INTEGER NOT NULL,
                    price REAL NOT NULL,
                    pnl REAL DEFAULT 0
                )
                """
            )
            conn.execute("CREATE TABLE IF NOT EXISTS reports (period TEXT PRIMARY KEY, generated_at TEXT NOT NULL, payload TEXT NOT NULL)")

    def record_equity(self, equity: float) -> None:
        """Record a point in the equity curve."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR REPLACE INTO equity_curve VALUES (?, ?)", (datetime.now(timezone.utc).isoformat(), equity))

    def equity_curve(self) -> pd.DataFrame:
        """Return recorded equity history."""
        with sqlite3.connect(self.db_path) as conn:
            return pd.read_sql_query("SELECT * FROM equity_curve ORDER BY timestamp", conn, parse_dates=["timestamp"])

    def recent_trades(self, limit: int = 50) -> pd.DataFrame:
        """Return the latest trade rows."""
        with sqlite3.connect(self.db_path) as conn:
            return pd.read_sql_query("SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", conn, params=(limit,))

    def calculate_metrics(self) -> dict[str, float]:
        """Calculate win rate, Sharpe ratio, and max drawdown."""
        equity = self.equity_curve()
        trades = self.recent_trades(500)
        returns = equity["equity"].pct_change().dropna() if not equity.empty else pd.Series(dtype=float)
        sharpe = float((returns.mean() / returns.std()) * np.sqrt(252)) if len(returns) > 1 and returns.std() else 0.0
        drawdown = 0.0
        if not equity.empty:
            running_max = equity["equity"].cummax()
            drawdown = float(((equity["equity"] - running_max) / running_max).min())
        win_rate = float((trades["pnl"] > 0).mean()) if not trades.empty else 0.0
        return {"win_rate": win_rate, "sharpe": sharpe, "max_drawdown": drawdown}

    def save_report(self, period: str) -> None:
        """Save a JSON-like metrics report for a period."""
        metrics = self.calculate_metrics()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR REPLACE INTO reports VALUES (?, ?, ?)", (period, datetime.now(timezone.utc).isoformat(), str(metrics)))

    def export_csv(self, path: str = "data/equity_curve.csv") -> str:
        """Export the equity curve to CSV and return the output path."""
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        self.equity_curve().to_csv(output, index=False)
        return str(output)

    def portfolio_value_from_account(self, account: Any) -> float:
        """Extract portfolio value from an Alpaca account-like object."""
        try:
            return float(account.portfolio_value)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unable to read portfolio value: %s", exc)
            return 0.0
