"""Broker connectivity, order placement, and order logging."""

from __future__ import annotations

import math
import sqlite3
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Optional

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetOrdersRequest, LimitOrderRequest, StopLossRequest, TakeProfitRequest

from config import Settings
from logging_utils import configure_logging
from strategy_engine import TradeSignal

logger = configure_logging()


class ExecutionEngine:
    """Submit live or paper orders to Alpaca and persist broker order history."""

    def __init__(self, settings: Settings) -> None:
        """Initialize Alpaca trading/data clients and SQLite order log."""
        settings.validate(require_credentials=True)
        self.settings = settings
        if settings.is_real_money_enabled():
            logger.critical("LIVE TRADING ENABLED. ORDERS WILL USE REAL MONEY.")
        self.client = TradingClient(settings.alpaca_api_key, settings.alpaca_secret_key, paper=not settings.live_mode)
        self.data_client = StockHistoricalDataClient(settings.alpaca_api_key, settings.alpaca_secret_key)
        self.db_path = Path(settings.database_path)
        self._init_db()

    def _init_db(self) -> None:
        """Create the orders table if it does not already exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty INTEGER NOT NULL,
                    limit_price REAL NOT NULL,
                    strategy TEXT NOT NULL,
                    status TEXT NOT NULL,
                    broker_order_id TEXT,
                    take_profit_price REAL,
                    stop_loss_price REAL,
                    order_class TEXT
                )
                """
            )
            self._ensure_column(conn, "orders", "take_profit_price", "REAL")
            self._ensure_column(conn, "orders", "stop_loss_price", "REAL")
            self._ensure_column(conn, "orders", "order_class", "TEXT")

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        """Add a SQLite column when upgrading an existing database."""
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def get_account(self) -> Any:
        """Return the Alpaca account object."""
        return self.client.get_account()

    def get_positions(self) -> list[Any]:
        """Return current Alpaca positions."""
        try:
            return list(self.client.get_all_positions())
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to fetch positions: %s", exc)
            return []

    def close_all_positions(self) -> None:
        """Submit broker liquidation requests for all open Alpaca positions."""
        try:
            self.client.close_all_positions(cancel_orders=True)
            logger.warning("All positions closed by risk control")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to close all positions: %s", exc)

    def get_latest_quote(self, symbol: str) -> tuple[float, float]:
        """Return latest Alpaca bid and ask prices for a symbol."""
        try:
            feed = DataFeed.SIP if self.settings.alpaca_data_feed.lower() == "sip" else DataFeed.IEX
            request = StockLatestQuoteRequest(symbol_or_symbols=symbol, feed=feed)
            quotes = self.data_client.get_stock_latest_quote(request)
            quote = quotes[symbol]
            return float(quote.bid_price), float(quote.ask_price)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Latest quote fetch failed for %s: %s", symbol, exc)
            return 0.0, 0.0

    def calculate_limit_price(self, bid: float, ask: float, side: str) -> float:
        """Calculate a two-decimal limit price inside the bid-ask spread."""
        if bid <= 0 or ask <= 0 or ask < bid:
            reference = max(bid, ask, 0.01)
            return self._round_price(reference)
        midpoint = (bid + ask) / 2
        price = midpoint if side.lower() == "buy" else max(bid, midpoint)
        return self._round_price(price)

    def build_protection_prices(self, entry_price: float, signal: TradeSignal) -> tuple[Optional[float], Optional[float]]:
        """Calculate take-profit and stop-loss prices from a signal."""
        if entry_price <= 0:
            return None, None
        take_profit = self._round_price(entry_price * (1 + signal.take_profit_pct)) if signal.take_profit_pct > 0 else None
        stop_loss_pct = signal.stop_loss_pct or signal.trailing_stop_pct
        stop_loss = self._round_price(entry_price * (1 - stop_loss_pct)) if stop_loss_pct > 0 else None
        return take_profit, stop_loss

    def submit_limit_order(self, signal: TradeSignal, qty: int, bid: float, ask: float, max_retries: int = 3) -> Optional[str]:
        """Submit a live/paper limit order with optional bracket protection and retry handling."""
        if qty <= 0:
            logger.warning("Order skipped for %s because quantity is zero", signal.symbol)
            return None
        limit_price = self.calculate_limit_price(bid, ask, signal.side.value)
        take_profit_price, stop_loss_price = self.build_protection_prices(limit_price, signal)
        request_kwargs: dict[str, Any] = {
            "symbol": signal.symbol,
            "qty": qty,
            "side": OrderSide.BUY if signal.side.value == "buy" else OrderSide.SELL,
            "time_in_force": TimeInForce.DAY,
            "limit_price": limit_price,
        }
        order_class = "simple"
        if self.settings.use_bracket_orders and signal.side.value == "buy" and take_profit_price and stop_loss_price:
            request_kwargs["order_class"] = OrderClass.BRACKET
            request_kwargs["take_profit"] = TakeProfitRequest(limit_price=take_profit_price)
            request_kwargs["stop_loss"] = StopLossRequest(stop_price=stop_loss_price)
            order_class = "bracket"
        request = LimitOrderRequest(**request_kwargs)
        for attempt in range(max_retries):
            try:
                order = self.client.submit_order(order_data=request)
                broker_id = str(order.id)
                self.log_order(signal, qty, limit_price, str(order.status), broker_id, take_profit_price, stop_loss_price, order_class)
                return broker_id
            except Exception as exc:  # noqa: BLE001
                logger.exception("Order attempt %s failed for %s: %s", attempt + 1, signal.symbol, exc)
                time.sleep(math.pow(2, attempt))
        self.log_order(signal, qty, limit_price, "failed", None, take_profit_price, stop_loss_price, order_class)
        return None

    def cancel_stale_open_orders(self) -> int:
        """Cancel open day orders older than the configured timeout and return count."""
        cancelled = 0
        try:
            request = GetOrdersRequest(status=QueryOrderStatus.OPEN)
            for order in self.client.get_orders(filter=request):
                submitted = order.submitted_at
                if submitted and (datetime.now(timezone.utc) - submitted).total_seconds() > self.settings.order_timeout_seconds:
                    self.client.cancel_order_by_id(order.id)
                    cancelled += 1
            return cancelled
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to cancel stale orders: %s", exc)
            return cancelled

    def log_order(
        self,
        signal: TradeSignal,
        qty: int,
        price: float,
        status: str,
        broker_order_id: Optional[str],
        take_profit_price: Optional[float] = None,
        stop_loss_price: Optional[float] = None,
        order_class: str = "simple",
    ) -> None:
        """Persist every order attempt to SQLite."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO orders (
                        timestamp, symbol, side, qty, limit_price, strategy, status, broker_order_id,
                        take_profit_price, stop_loss_price, order_class
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        datetime.now(timezone.utc).isoformat(),
                        signal.symbol,
                        signal.side.value,
                        qty,
                        price,
                        signal.strategy,
                        status,
                        broker_order_id,
                        take_profit_price,
                        stop_loss_price,
                        order_class,
                    ),
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to log order: %s", exc)

    def handle_partial_fills(self, order_id: str) -> str:
        """Return a readable status for a potentially partially filled Alpaca order."""
        try:
            order = self.client.get_order_by_id(order_id)
            return f"status={order.status}, filled={order.filled_qty}, remaining={float(order.qty) - float(order.filled_qty)}"
        except Exception as exc:  # noqa: BLE001
            logger.exception("Partial fill check failed for %s: %s", order_id, exc)
            return "unknown"

    def _round_price(self, price: float) -> float:
        """Round a stock price to cents using decimal half-up behavior."""
        return float(Decimal(str(price)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
