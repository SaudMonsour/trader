"""Market data retrieval and indicator calculation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List

import pandas as pd
import yfinance as yf
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD
from ta.volatility import AverageTrueRange, BollingerBands

from logging_utils import configure_logging

logger = configure_logging()


@dataclass
class GapResult:
    """Represents a pre-market gap scan result."""

    symbol: str
    previous_close: float
    current_price: float
    gap_pct: float


class DataEngine:
    """Fetch OHLCV data and enrich it with technical indicators."""

    def __init__(self, watchlist: Iterable[str]) -> None:
        """Initialize the data engine with a stock watchlist."""
        self.watchlist = list(dict.fromkeys(symbol.upper() for symbol in watchlist))

    def fetch_ohlcv(self, symbol: str, period: str = "3mo", interval: str = "5m") -> pd.DataFrame:
        """Fetch OHLCV bars from yfinance for one symbol."""
        try:
            data = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=True)
            if data.empty:
                logger.warning("No OHLCV data returned for %s", symbol)
                return pd.DataFrame()
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
            data = data.rename(columns=str.lower)
            data["symbol"] = symbol.upper()
            return data.dropna()
        except Exception as exc:  # noqa: BLE001 - production data boundary logs all provider errors.
            logger.exception("Failed to fetch OHLCV for %s: %s", symbol, exc)
            return pd.DataFrame()

    def fetch_watchlist(self, period: str = "3mo", interval: str = "5m") -> Dict[str, pd.DataFrame]:
        """Fetch enriched market data for every symbol in the watchlist."""
        frames: Dict[str, pd.DataFrame] = {}
        for symbol in self.watchlist:
            raw = self.fetch_ohlcv(symbol, period=period, interval=interval)
            frames[symbol] = self.compute_indicators(raw) if not raw.empty else raw
        return frames

    def compute_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """Add RSI, MACD, Bollinger Bands, EMAs, ATR, and volume spike features."""
        try:
            df = data.copy()
            if len(df) < 50:
                return df
            close = df["close"]
            high = df["high"]
            low = df["low"]
            volume = df["volume"]

            df["rsi_14"] = RSIIndicator(close=close, window=14).rsi()
            macd = MACD(close=close)
            df["macd"] = macd.macd()
            df["macd_signal"] = macd.macd_signal()
            df["macd_diff"] = macd.macd_diff()
            bb = BollingerBands(close=close, window=20, window_dev=2)
            df["bb_high"] = bb.bollinger_hband()
            df["bb_mid"] = bb.bollinger_mavg()
            df["bb_low"] = bb.bollinger_lband()
            for window in (9, 21, 50):
                df[f"ema_{window}"] = EMAIndicator(close=close, window=window).ema_indicator()
            df["atr_14"] = AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range()
            df["avg_volume_20"] = volume.rolling(20).mean()
            df["volume_spike"] = volume > (df["avg_volume_20"] * 2)
            df["twenty_day_high"] = high.rolling(20).max().shift(1)
            return df.dropna()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Indicator calculation failed: %s", exc)
            return data

    def scan_premarket_gaps(self, threshold_pct: float = 2.0) -> List[GapResult]:
        """Return watchlist symbols whose latest price gaps more than threshold from prior close."""
        gaps: List[GapResult] = []
        for symbol in self.watchlist:
            try:
                daily = yf.download(symbol, period="5d", interval="1d", progress=False, auto_adjust=True)
                intraday = yf.download(symbol, period="1d", interval="1m", progress=False, auto_adjust=True)
                if len(daily) < 2 or intraday.empty:
                    continue
                previous_close = float(daily["Close"].iloc[-2])
                current_price = float(intraday["Close"].dropna().iloc[-1])
                gap_pct = ((current_price - previous_close) / previous_close) * 100
                if abs(gap_pct) >= threshold_pct:
                    gaps.append(GapResult(symbol, previous_close, current_price, gap_pct))
            except Exception as exc:  # noqa: BLE001
                logger.exception("Gap scan failed for %s: %s", symbol, exc)
        return gaps
