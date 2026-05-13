"""QuantumEdge autonomous trading agent entry point."""

from __future__ import annotations

from datetime import datetime
from time import sleep

from apscheduler.schedulers.background import BackgroundScheduler

from ai_signal_enhancer import AISignalEnhancer
from config import get_settings
from data_engine import DataEngine
from execution_engine import ExecutionEngine
from logging_utils import configure_logging
from portfolio_tracker import PortfolioTracker
from risk_manager import EASTERN, RiskManager
from strategy_engine import SignalSide, StrategyEngine

logger = configure_logging()


class QuantumEdgeBot:
    """Coordinate data, strategy, risk, ML scoring, execution, and reporting."""

    def __init__(self) -> None:
        """Initialize all runtime modules."""
        self.settings = get_settings(require_credentials=True)
        self.data_engine = DataEngine(self.settings.watchlist)
        self.strategy_engine = StrategyEngine()
        self.risk_manager = RiskManager(self.settings)
        self.ai = AISignalEnhancer()
        self.execution = ExecutionEngine(self.settings)
        self.tracker = PortfolioTracker(self.settings)
        self.scheduler = BackgroundScheduler(timezone=str(EASTERN))
        self.running = False
        self.starting_equity = 0.0

    def start(self) -> None:
        """Start scheduled jobs for autonomous trading."""
        account = self.execution.get_account()
        self.starting_equity = float(account.portfolio_value)
        self.running = True
        self.scheduler.add_job(self.market_scan, "interval", minutes=5, id="market_scan", replace_existing=True)
        self.scheduler.add_job(self.risk_check, "interval", minutes=1, id="risk_check", replace_existing=True)
        self.scheduler.add_job(self.daily_report, "cron", hour=16, minute=30, id="daily_report", replace_existing=True)
        self.scheduler.add_job(self.weekly_retrain, "cron", day_of_week="sun", hour=9, minute=0, id="weekly_retrain", replace_existing=True)
        self.scheduler.start()
        logger.info("QuantumEdge started in %s mode", "LIVE" if self.settings.live_mode else "PAPER")

    def stop(self) -> None:
        """Stop scheduled jobs without liquidating positions."""
        self.running = False
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        logger.info("QuantumEdge stopped")

    def market_scan(self) -> None:
        """Scan the market and execute qualified strategy signals."""
        if not self.running:
            return
        try:
            account = self.execution.get_account()
            current_equity = float(account.portfolio_value)
            open_positions = len(self.execution.get_positions())
            ok, reason = self.risk_manager.pre_trade_check(self.starting_equity, current_equity, open_positions)
            if not ok:
                logger.warning("Market scan skipped: %s", reason)
                return
            frames = self.data_engine.fetch_watchlist()
            for symbol, frame in frames.items():
                if frame.empty:
                    continue
                signal = self.strategy_engine.select_signal(symbol, frame)
                if signal.side == SignalSide.HOLD:
                    continue
                regime = self.strategy_engine.detect_market_regime(frame)
                features = self.ai.build_feature_row(frame.iloc[-1], self.tracker.calculate_metrics()["win_rate"], regime)
                confidence = max(signal.confidence_hint, self.ai.score_signal(features))
                if confidence < self.settings.min_confidence:
                    logger.info("Signal rejected for %s: confidence %.1f", symbol, confidence)
                    continue
                price = float(frame["close"].iloc[-1])
                bid, ask = self.execution.get_latest_quote(symbol)
                if bid <= 0 or ask <= 0:
                    bid, ask = price * 0.999, price * 1.001
                qty = self.risk_manager.kelly_position_size(current_equity, confidence / 100, 1.5, price)
                self.execution.submit_limit_order(signal, qty, bid, ask)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Market scan failed: %s", exc)

    def risk_check(self) -> None:
        """Run continuous risk checks and end-of-day liquidation."""
        try:
            account = self.execution.get_account()
            current_equity = float(account.portfolio_value)
            self.tracker.record_equity(current_equity)
            self.execution.cancel_stale_open_orders()
            if not self.risk_manager.enforce_daily_loss_limit(self.starting_equity, current_equity):
                self.execution.close_all_positions()
                self.running = False
            self.risk_manager.liquidate_if_needed(self.execution, datetime.now(EASTERN))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Risk check failed: %s", exc)

    def daily_report(self) -> None:
        """Generate and persist the daily performance report."""
        self.tracker.save_report("daily")
        logger.info("Daily report saved")

    def weekly_retrain(self) -> None:
        """Retrain the confidence model on recent watchlist data."""
        frames = self.data_engine.fetch_watchlist(period="6mo", interval="1d").values()
        if self.ai.retrain_weekly(frames):
            logger.info("Weekly model retrain completed")


def main() -> None:
    """Run the bot as a foreground service until interrupted."""
    bot = QuantumEdgeBot()
    bot.start()
    try:
        while True:
            sleep(1)
    except KeyboardInterrupt:
        bot.stop()


if __name__ == "__main__":
    main()
