"""Unit tests for mandatory risk controls."""

from __future__ import annotations

from datetime import datetime

from config import Settings
from risk_manager import EASTERN, RiskManager


class DummyBroker:
    """Broker test double that records liquidation calls."""

    def __init__(self) -> None:
        """Initialize call counter."""
        self.closed = False

    def close_all_positions(self) -> None:
        """Record that close-all was called."""
        self.closed = True


def test_daily_loss_limit_halts_trading() -> None:
    """Daily loss breaches should halt new trading."""
    manager = RiskManager(Settings())
    assert manager.enforce_daily_loss_limit(100_000, 97_500) is False
    assert manager.state.trading_halted is True


def test_trading_window_blocks_first_and_last_15_minutes() -> None:
    """Trading should be blocked during the opening and closing buffers."""
    manager = RiskManager(Settings())
    assert manager.is_within_trading_window(datetime(2026, 5, 11, 9, 40, tzinfo=EASTERN)) is False
    assert manager.is_within_trading_window(datetime(2026, 5, 11, 10, 0, tzinfo=EASTERN)) is True
    assert manager.is_within_trading_window(datetime(2026, 5, 11, 15, 50, tzinfo=EASTERN)) is False


def test_vix_halt() -> None:
    """VIX above the configured threshold should fail risk checks."""
    manager = RiskManager(Settings())
    assert manager.is_vix_safe(31.0) is False
    assert manager.state.halt_reason == "VIX too high"


def test_kelly_position_size_is_capped() -> None:
    """Kelly position sizing should not exceed the configured max position percentage."""
    manager = RiskManager(Settings(max_position_pct=0.05))
    qty = manager.kelly_position_size(100_000, 0.70, 2.0, 100.0)
    assert qty == 50


def test_eod_liquidation_calls_broker() -> None:
    """EOD liquidation should close positions at 3:45 PM ET or later before close."""
    manager = RiskManager(Settings())
    broker = DummyBroker()
    did_liquidate = manager.liquidate_if_needed(broker, datetime(2026, 5, 11, 15, 45, tzinfo=EASTERN))
    assert did_liquidate is True
    assert broker.closed is True


def test_pre_trade_check_blocks_max_positions() -> None:
    """Pre-trade checks should block trades when max positions are already open."""
    manager = RiskManager(Settings(max_concurrent_positions=3))
    ok, reason = manager.pre_trade_check(
        100_000,
        100_000,
        3,
        now=datetime(2026, 5, 11, 10, 0, tzinfo=EASTERN),
        vix=20.0,
    )
    assert ok is False
    assert reason == "Max concurrent positions reached"
