"""Trading strategy implementations and market-regime selection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional

import pandas as pd

from logging_utils import configure_logging

logger = configure_logging()


class SignalSide(str, Enum):
    """Supported signal directions."""

    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class TradeSignal:
    """Normalized strategy signal for execution and logging."""

    symbol: str
    side: SignalSide
    strategy: str
    confidence_hint: float
    reason: str
    stop_loss_pct: float = 0.0
    take_profit_pct: float = 0.0
    trailing_stop_pct: float = 0.0


class StrategyEngine:
    """Generate strategy signals and pause strategies after losing streaks."""

    def __init__(self) -> None:
        """Initialize daily strategy loss tracking."""
        self.daily_loss_streaks: Dict[str, int] = {
            "momentum_breakout": 0,
            "mean_reversion": 0,
            "trend_following": 0,
        }

    def record_trade_result(self, strategy: str, pnl: float) -> None:
        """Update the strategy loss streak using a completed trade PnL."""
        if strategy not in self.daily_loss_streaks:
            self.daily_loss_streaks[strategy] = 0
        self.daily_loss_streaks[strategy] = self.daily_loss_streaks[strategy] + 1 if pnl < 0 else 0

    def is_strategy_paused(self, strategy: str) -> bool:
        """Return True if a strategy has lost at least three trades in a row today."""
        return self.daily_loss_streaks.get(strategy, 0) >= 3

    def reset_daily_streaks(self) -> None:
        """Clear all strategy loss streaks at the start of a new trading day."""
        for strategy in self.daily_loss_streaks:
            self.daily_loss_streaks[strategy] = 0

    def momentum_breakout(self, symbol: str, data: pd.DataFrame) -> TradeSignal:
        """Strategy A: buy breakouts above the prior 20-bar high on strong volume."""
        strategy = "momentum_breakout"
        if self.is_strategy_paused(strategy) or len(data) < 21:
            return self._hold(symbol, strategy, "paused or insufficient data")
        latest = data.iloc[-1]
        price_break = latest["close"] > latest.get("twenty_day_high", float("inf"))
        volume_break = bool(latest.get("volume_spike", False))
        rsi_ok = 50 <= latest.get("rsi_14", 0) <= 70
        if price_break and volume_break and rsi_ok:
            return TradeSignal(symbol, SignalSide.BUY, strategy, 75, "20-day high breakout with volume", 0.008, 0.015)
        if latest.get("rsi_14", 0) > 80:
            return TradeSignal(symbol, SignalSide.SELL, strategy, 70, "RSI exit above 80")
        return self._hold(symbol, strategy, "breakout conditions not met")

    def mean_reversion(self, symbol: str, data: pd.DataFrame) -> TradeSignal:
        """Strategy B: buy oversold lower Bollinger Band touches with declining volume."""
        strategy = "mean_reversion"
        if self.is_strategy_paused(strategy) or len(data) < 21:
            return self._hold(symbol, strategy, "paused or insufficient data")
        latest = data.iloc[-1]
        previous = data.iloc[-2]
        volume_declining = latest["volume"] < previous["volume"]
        if latest.get("rsi_14", 100) < 30 and latest["close"] <= latest.get("bb_low", 0) and volume_declining:
            return TradeSignal(symbol, SignalSide.BUY, strategy, 72, "oversold lower Bollinger Band touch", 0.005, 0.01)
        if latest["close"] >= latest.get("bb_mid", float("inf")):
            return TradeSignal(symbol, SignalSide.SELL, strategy, 68, "price returned to middle Bollinger Band")
        return self._hold(symbol, strategy, "mean reversion conditions not met")

    def trend_following(self, symbol: str, data: pd.DataFrame) -> TradeSignal:
        """Strategy C: buy EMA9 crosses above EMA21 while price is above EMA50."""
        strategy = "trend_following"
        if self.is_strategy_paused(strategy) or len(data) < 51:
            return self._hold(symbol, strategy, "paused or insufficient data")
        latest = data.iloc[-1]
        previous = data.iloc[-2]
        cross_up = previous["ema_9"] <= previous["ema_21"] and latest["ema_9"] > latest["ema_21"]
        cross_down = previous["ema_9"] >= previous["ema_21"] and latest["ema_9"] < latest["ema_21"]
        if cross_up and latest["close"] > latest["ema_50"]:
            return TradeSignal(symbol, SignalSide.BUY, strategy, 73, "EMA9 crossed above EMA21 above EMA50", trailing_stop_pct=0.01)
        if cross_down:
            return TradeSignal(symbol, SignalSide.SELL, strategy, 70, "EMA9 crossed below EMA21")
        return self._hold(symbol, strategy, "trend conditions not met")

    def detect_market_regime(self, data: pd.DataFrame) -> str:
        """Classify a symbol as trending, ranging, or volatile using EMA slope and ATR."""
        try:
            if len(data) < 50:
                return "ranging"
            latest = data.iloc[-1]
            atr_pct = latest.get("atr_14", 0) / max(latest["close"], 0.01)
            ema_slope = data["ema_50"].iloc[-1] - data["ema_50"].iloc[-10]
            if atr_pct > 0.04:
                return "volatile"
            if abs(ema_slope) / max(latest["close"], 0.01) > 0.005:
                return "trending"
            return "ranging"
        except Exception as exc:  # noqa: BLE001
            logger.exception("Regime detection failed: %s", exc)
            return "ranging"

    def select_signal(self, symbol: str, data: pd.DataFrame) -> TradeSignal:
        """Select the best strategy for the current market regime and return its signal."""
        regime = self.detect_market_regime(data)
        if regime == "trending":
            signal = self.trend_following(symbol, data)
            return signal if signal.side != SignalSide.HOLD else self.momentum_breakout(symbol, data)
        if regime == "volatile":
            return self._hold(symbol, "risk_filter", "volatile symbol regime")
        signal = self.mean_reversion(symbol, data)
        return signal if signal.side != SignalSide.HOLD else self.momentum_breakout(symbol, data)

    def _hold(self, symbol: str, strategy: str, reason: str) -> TradeSignal:
        """Create a hold signal."""
        return TradeSignal(symbol, SignalSide.HOLD, strategy, 0, reason)
