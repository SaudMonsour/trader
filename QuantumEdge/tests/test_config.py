"""Unit tests for live-trading configuration safeguards."""

from __future__ import annotations

import pytest

from config import Settings


def test_live_mode_requires_live_url() -> None:
    """Live mode should reject the paper broker URL."""
    settings = Settings(
        alpaca_api_key="key",
        alpaca_secret_key="secret",
        live_mode=True,
        alpaca_base_url="https://paper-api.alpaca.markets",
        live_trading_ack="I_UNDERSTAND_REAL_MONEY_RISK",
    )
    with pytest.raises(ValueError, match="live Alpaca"):
        settings.validate(require_credentials=True)


def test_live_mode_requires_real_money_ack() -> None:
    """Live mode should require an explicit real-money acknowledgement."""
    settings = Settings(
        alpaca_api_key="key",
        alpaca_secret_key="secret",
        live_mode=True,
        alpaca_base_url="https://api.alpaca.markets",
        live_trading_ack="",
    )
    with pytest.raises(ValueError, match="LIVE_TRADING_ACK"):
        settings.validate(require_credentials=True)


def test_live_mode_real_money_enabled_when_acknowledged() -> None:
    """Live mode should be recognized as real-money mode after all safeguards pass."""
    settings = Settings(
        alpaca_api_key="key",
        alpaca_secret_key="secret",
        live_mode=True,
        alpaca_base_url="https://api.alpaca.markets",
        live_trading_ack="I_UNDERSTAND_REAL_MONEY_RISK",
    )
    settings.validate(require_credentials=True)
    assert settings.is_real_money_enabled() is True
