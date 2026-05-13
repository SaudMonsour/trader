"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from typing import List

from dotenv import load_dotenv

load_dotenv()


def _get_float(name: str, default: float) -> float:
    """Return an environment variable as float with a safe default."""
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _get_int(name: str, default: int) -> int:
    """Return an environment variable as integer with a safe default."""
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _get_bool(name: str, default: bool = False) -> bool:
    """Return an environment variable as boolean."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_watchlist() -> List[str]:
    """Return configured uppercase symbols from WATCHLIST."""
    raw = os.getenv("WATCHLIST", "SPY,QQQ,AAPL,TSLA,NVDA,AMD,MSFT")
    return [symbol.strip().upper() for symbol in raw.split(",") if symbol.strip()]


@dataclass(frozen=True)
class Settings:
    """Runtime settings for the trading system."""

    alpaca_api_key: str = os.getenv("ALPACA_API_KEY", "")
    alpaca_secret_key: str = os.getenv("ALPACA_SECRET_KEY", "")
    alpaca_base_url: str = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    alpaca_data_feed: str = os.getenv("ALPACA_DATA_FEED", "iex")
    live_mode: bool = _get_bool("LIVE_MODE", False)
    live_trading_ack: str = os.getenv("LIVE_TRADING_ACK", "")
    require_live_trading_ack: bool = _get_bool("REQUIRE_LIVE_TRADING_ACK", True)
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    database_path: Path = Path(os.getenv("DATABASE_PATH", "data/quantumedge.db"))
    log_file: str = os.getenv("LOG_FILE", "logs/trading.log")
    watchlist: List[str] = field(default_factory=_get_watchlist)
    max_daily_loss_pct: float = _get_float("MAX_DAILY_LOSS_PCT", 0.02)
    max_position_pct: float = _get_float("MAX_POSITION_PCT", 0.05)
    target_daily_return_pct: float = _get_float("TARGET_DAILY_RETURN_PCT", 0.02)
    max_concurrent_positions: int = _get_int("MAX_CONCURRENT_POSITIONS", 3)
    min_confidence: float = _get_float("MIN_CONFIDENCE", 65.0)
    vix_halt_level: float = _get_float("VIX_HALT_LEVEL", 30.0)
    order_timeout_seconds: int = _get_int("ORDER_TIMEOUT_SECONDS", 60)
    use_bracket_orders: bool = _get_bool("USE_BRACKET_ORDERS", True)
    market_open_et: time = time(9, 30)
    market_close_et: time = time(16, 0)
    no_trade_minutes_after_open: int = 15
    no_trade_minutes_before_close: int = 15
    liquidation_time_et: time = time(15, 45)

    def validate(self, require_credentials: bool = False) -> None:
        """Validate critical settings and optionally require broker credentials."""
        if require_credentials and (not self.alpaca_api_key or not self.alpaca_secret_key):
            raise ValueError("ALPACA_API_KEY and ALPACA_SECRET_KEY must be set before trading.")
        if self.live_mode and "paper" in self.alpaca_base_url:
            raise ValueError("LIVE_MODE=true requires ALPACA_BASE_URL=https://api.alpaca.markets.")
        if self.live_mode and self.require_live_trading_ack and self.live_trading_ack != "I_UNDERSTAND_REAL_MONEY_RISK":
            raise ValueError("Live trading requires LIVE_TRADING_ACK=I_UNDERSTAND_REAL_MONEY_RISK.")
        if self.max_daily_loss_pct <= 0 or self.max_position_pct <= 0:
            raise ValueError("Risk percentages must be positive.")
        if not self.watchlist:
            raise ValueError("WATCHLIST must contain at least one symbol.")

    def is_real_money_enabled(self) -> bool:
        """Return True when this configuration will place live broker orders."""
        return self.live_mode and "paper" not in self.alpaca_base_url


def get_settings(require_credentials: bool = False) -> Settings:
    """Build and validate settings from the process environment."""
    settings = Settings()
    settings.validate(require_credentials=require_credentials)
    return settings
