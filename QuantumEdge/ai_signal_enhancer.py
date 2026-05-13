"""Machine-learning confidence scoring for strategy signals."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from logging_utils import configure_logging

logger = configure_logging()
FEATURES: List[str] = [
    "rsi_14", "macd", "macd_signal", "macd_diff", "bb_high", "bb_mid", "bb_low",
    "ema_9", "ema_21", "ema_50", "atr_14", "volume", "avg_volume_20",
    "hour", "day_of_week", "recent_win_rate", "market_regime_code",
]


class AISignalEnhancer:
    """Train and serve Random Forest signal confidence scores."""

    def __init__(self, model_path: str = "data/signal_model.joblib") -> None:
        """Load an existing model or initialize an untrained pipeline."""
        self.model_path = Path(model_path)
        self.model = self._load_or_create_model()
        self.is_trained = self.model_path.exists()

    def _load_or_create_model(self) -> Pipeline:
        """Load a persisted model, or return a fresh Random Forest pipeline."""
        try:
            if self.model_path.exists():
                return joblib.load(self.model_path)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Model load failed, creating a new model: %s", exc)
        return Pipeline([
            ("scale", StandardScaler()),
            ("forest", RandomForestClassifier(n_estimators=200, max_depth=8, random_state=42, class_weight="balanced")),
        ])

    def build_feature_row(self, latest: pd.Series, recent_win_rate: float, market_regime: str) -> pd.DataFrame:
        """Build a one-row feature frame from latest indicators and context."""
        timestamp = latest.name if hasattr(latest, "name") else pd.Timestamp.utcnow()
        if not isinstance(timestamp, pd.Timestamp):
            timestamp = pd.Timestamp.utcnow()
        regime_code = {"ranging": 0, "trending": 1, "volatile": 2}.get(market_regime, 0)
        row = {feature: float(latest.get(feature, 0.0) or 0.0) for feature in FEATURES if feature not in {"hour", "day_of_week", "recent_win_rate", "market_regime_code"}}
        row.update({"hour": timestamp.hour, "day_of_week": timestamp.dayofweek, "recent_win_rate": recent_win_rate, "market_regime_code": regime_code})
        return pd.DataFrame([row], columns=FEATURES).fillna(0.0)

    def score_signal(self, feature_row: pd.DataFrame) -> float:
        """Return a 0-100 confidence score for a proposed trade."""
        try:
            if not self.is_trained:
                return 70.0
            probability = self.model.predict_proba(feature_row[FEATURES])[0][1]
            return float(np.clip(probability * 100, 0, 100))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Signal scoring failed: %s", exc)
            return 0.0

    def train(self, training_data: pd.DataFrame) -> bool:
        """Train the Random Forest on historical feature rows with a target column."""
        try:
            if training_data.empty or "target" not in training_data.columns:
                logger.warning("Training skipped: missing data or target")
                return False
            self.model.fit(training_data[FEATURES].fillna(0.0), training_data["target"].astype(int))
            self.model_path.parent.mkdir(parents=True, exist_ok=True)
            joblib.dump(self.model, self.model_path)
            self.is_trained = True
            return True
        except Exception as exc:  # noqa: BLE001
            logger.exception("Model training failed: %s", exc)
            return False

    def retrain_weekly(self, frames: Iterable[pd.DataFrame]) -> bool:
        """Retrain from recent enriched bars by labeling positive next-bar returns."""
        rows = []
        for frame in frames:
            if frame.empty:
                continue
            df = frame.copy()
            df["hour"] = pd.to_datetime(df.index).hour
            df["day_of_week"] = pd.to_datetime(df.index).dayofweek
            df["recent_win_rate"] = 0.5
            df["market_regime_code"] = 0
            df["target"] = (df["close"].shift(-1) > df["close"]).astype(int)
            rows.append(df.dropna())
        return self.train(pd.concat(rows)) if rows else False
