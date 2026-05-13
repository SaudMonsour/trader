"""Unit tests for strategy signal generation."""

from __future__ import annotations

import pandas as pd

from strategy_engine import SignalSide, StrategyEngine


def make_frame(rows: int = 60) -> pd.DataFrame:
    """Create a deterministic indicator frame for strategy tests."""
    index = pd.date_range("2026-01-01 10:00", periods=rows, freq="5min")
    data = pd.DataFrame(
        {
            "close": [100.0] * rows,
            "high": [101.0] * rows,
            "low": [99.0] * rows,
            "volume": [1000.0] * rows,
            "rsi_14": [55.0] * rows,
            "bb_low": [95.0] * rows,
            "bb_mid": [100.0] * rows,
            "ema_9": [100.0] * rows,
            "ema_21": [101.0] * rows,
            "ema_50": [99.0] * rows,
            "atr_14": [1.0] * rows,
            "volume_spike": [False] * rows,
            "twenty_day_high": [102.0] * rows,
        },
        index=index,
    )
    return data


def test_momentum_breakout_buy_signal() -> None:
    """Momentum breakout should buy on high breakout, volume spike, and valid RSI."""
    engine = StrategyEngine()
    frame = make_frame()
    frame.loc[frame.index[-1], ["close", "volume_spike", "twenty_day_high", "rsi_14"]] = [105.0, True, 103.0, 60.0]
    signal = engine.momentum_breakout("SPY", frame)
    assert signal.side == SignalSide.BUY
    assert signal.strategy == "momentum_breakout"
    assert signal.take_profit_pct == 0.015


def test_mean_reversion_buy_signal() -> None:
    """Mean reversion should buy when price is oversold at the lower band."""
    engine = StrategyEngine()
    frame = make_frame()
    frame.loc[frame.index[-2], "volume"] = 2000.0
    frame.loc[frame.index[-1], ["close", "bb_low", "rsi_14", "volume"]] = [94.0, 95.0, 25.0, 1000.0]
    signal = engine.mean_reversion("QQQ", frame)
    assert signal.side == SignalSide.BUY
    assert signal.stop_loss_pct == 0.005


def test_trend_following_buy_signal() -> None:
    """Trend following should buy on EMA9 crossing above EMA21 over EMA50."""
    engine = StrategyEngine()
    frame = make_frame()
    frame.loc[frame.index[-2], ["ema_9", "ema_21"]] = [99.0, 100.0]
    frame.loc[frame.index[-1], ["ema_9", "ema_21", "ema_50", "close"]] = [101.0, 100.0, 98.0, 102.0]
    signal = engine.trend_following("AAPL", frame)
    assert signal.side == SignalSide.BUY
    assert signal.trailing_stop_pct == 0.01


def test_strategy_pauses_after_three_losses() -> None:
    """A strategy should pause automatically after three consecutive losses."""
    engine = StrategyEngine()
    for _ in range(3):
        engine.record_trade_result("momentum_breakout", -1.0)
    signal = engine.momentum_breakout("SPY", make_frame())
    assert engine.is_strategy_paused("momentum_breakout") is True
    assert signal.side == SignalSide.HOLD
