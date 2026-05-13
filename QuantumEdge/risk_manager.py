"""Pre-trade, intraday, and end-of-day risk controls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

import yfinance as yf

from config import Settings
from logging_utils import configure_logging

logger = configure_logging()
EASTERN = ZoneInfo("America/New_York")


class BrokerLike(Protocol):
    """Minimal broker protocol used by the risk manager."""

    def close_all_positions(self) -> None:
        """Close all open positions."""


@dataclass
class RiskState:
    """Current risk status displayed in the dashboard."""

    trading_halted: bool = False
    halt_reason: str = ""
    daily_pnl_pct: float = 0.0
    current_vix: float = 0.0


class RiskManager:
    """Enforce hard risk limits before any trade reaches the broker."""

    def __init__(self, settings: Settings) -> None:
        """Initialize risk limits from settings."""
        self.settings = settings
        self.state = RiskState()

    def calculate_daily_pnl_pct(self, starting_equity: float, current_equity: float) -> float:
        """Calculate daily PnL as a percentage of starting equity."""
        if starting_equity <= 0:
            return 0.0
        return (current_equity - starting_equity) / starting_equity

    def enforce_daily_loss_limit(self, starting_equity: float, current_equity: float) -> bool:
        """Halt trading when daily PnL breaches the configured loss limit."""
        pnl_pct = self.calculate_daily_pnl_pct(starting_equity, current_equity)
        self.state.daily_pnl_pct = pnl_pct
        if pnl_pct <= -abs(self.settings.max_daily_loss_pct):
            self.state.trading_halted = True
            self.state.halt_reason = "Daily loss limit breached"
            logger.critical("Trading halted: daily PnL %.2f%%", pnl_pct * 100)
            return False
        return True

    def is_within_trading_window(self, now: datetime | None = None) -> bool:
        """Return True when trading is allowed outside opening and closing buffers."""
        current = now.astimezone(EASTERN) if now else datetime.now(EASTERN)
        open_dt = datetime.combine(current.date(), self.settings.market_open_et, tzinfo=EASTERN)
        close_dt = datetime.combine(current.date(), self.settings.market_close_et, tzinfo=EASTERN)
        start = open_dt + timedelta(minutes=self.settings.no_trade_minutes_after_open)
        end = close_dt - timedelta(minutes=self.settings.no_trade_minutes_before_close)
        return start <= current <= end

    def should_liquidate_eod(self, now: datetime | None = None) -> bool:
        """Return True at or after the configured end-of-day liquidation time."""
        current = now.astimezone(EASTERN) if now else datetime.now(EASTERN)
        liquidation_dt = datetime.combine(current.date(), self.settings.liquidation_time_et, tzinfo=EASTERN)
        close_dt = datetime.combine(current.date(), self.settings.market_close_et, tzinfo=EASTERN)
        return liquidation_dt <= current < close_dt

    def fetch_vix(self) -> float:
        """Fetch the latest VIX close from yfinance, returning zero on failure."""
        try:
            data = yf.download("^VIX", period="5d", interval="1d", progress=False, auto_adjust=True)
            if data.empty:
                return 0.0
            value = float(data["Close"].dropna().iloc[-1])
            self.state.current_vix = value
            return value
        except Exception as exc:  # noqa: BLE001
            logger.exception("VIX fetch failed: %s", exc)
            return 0.0

    def is_vix_safe(self, vix: float | None = None) -> bool:
        """Return False when VIX is above the configured volatility halt level."""
        current_vix = self.fetch_vix() if vix is None else vix
        self.state.current_vix = current_vix
        if current_vix > self.settings.vix_halt_level:
            self.state.trading_halted = True
            self.state.halt_reason = "VIX too high"
            return False
        return True

    def max_positions_ok(self, open_positions: int) -> bool:
        """Return True if another position may be opened."""
        return open_positions < self.settings.max_concurrent_positions

    def kelly_position_size(
        self,
        portfolio_value: float,
        win_probability: float,
        win_loss_ratio: float,
        price: float,
    ) -> int:
        """Calculate share quantity using capped fractional Kelly sizing."""
        if portfolio_value <= 0 or price <= 0 or win_loss_ratio <= 0:
            return 0
        kelly_fraction = win_probability - ((1 - win_probability) / win_loss_ratio)
        capped_fraction = max(0.0, min(kelly_fraction * 0.5, self.settings.max_position_pct))
        dollar_size = portfolio_value * capped_fraction
        return int(dollar_size // price)

    def pre_trade_check(
        self,
        starting_equity: float,
        current_equity: float,
        open_positions: int,
        now: datetime | None = None,
        vix: float | None = None,
    ) -> tuple[bool, str]:
        """Run every mandatory risk check before a new order is submitted."""
        checks = [
            (self.enforce_daily_loss_limit(starting_equity, current_equity), self.state.halt_reason or "Daily loss OK"),
            (self.is_within_trading_window(now), "Trading window OK"),
            (self.is_vix_safe(vix), self.state.halt_reason or "VIX OK"),
            (self.max_positions_ok(open_positions), "Max concurrent positions reached"),
        ]
        for passed, message in checks:
            if not passed:
                return False, message
        return True, "All risk checks passed"

    def liquidate_if_needed(self, broker: BrokerLike, now: datetime | None = None) -> bool:
        """Close all broker positions if the liquidation time has arrived."""
        if self.should_liquidate_eod(now):
            broker.close_all_positions()
            return True
        return False
