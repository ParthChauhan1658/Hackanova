"""
IsolationForestWrapper — loads the serialised IF model at startup
and provides a single score() method for SL5 anomaly detection.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from app.core.constants import (
    IF_POINTS_HIGH,
    IF_POINTS_LOW,
    IF_POINTS_MID,
    IF_SCORE_HIGH_THRESHOLD,
    IF_SCORE_LOW_THRESHOLD,
    IF_SCORE_MID_THRESHOLD,
)
from app.models.assessment import ScoreContributor, SL5Result

logger = logging.getLogger(__name__)

# Population means used to substitute None features
_FEATURE_MEANS = {
    "heart_rate":       72.0,
    "respiratory_rate": 16.0,
    "spo2":             98.0,
    "body_temperature": 37.0,
    "hrv_ms":           55.0,
    "stress_score":     25.0,
    "steps_per_hour":   2000.0,
}

# Feature normalisation formulas
def _normalise_features(raw: dict[str, float]) -> list[float]:
    return [
        (raw["heart_rate"]       - 40.0) / 160.0,
        (raw["respiratory_rate"] - 6.0)  / 34.0,
        (raw["spo2"]             - 80.0) / 20.0,
        (raw["body_temperature"] - 34.0) / 8.0,
        raw["hrv_ms"]            / 100.0,
        raw["stress_score"]      / 100.0,
        min(raw["steps_per_hour"], 8000.0) / 8000.0,
    ]


class IsolationForestWrapper:
    """
    Loads sentinel_if.pkl once at startup and scores vital vectors for SL5.
    If the pkl file is missing, is_loaded stays False and score() returns 0 pts.
    """

    def __init__(
        self,
        model_path: str = "backend/app/ml/sentinel_if.pkl",
    ) -> None:
        self._model_path = model_path
        self._model = None
        self._raw_min: float = -0.5
        self._raw_max: float = 0.5
        self._loaded: bool = False

    def load(self) -> None:
        """Load model + raw_min/raw_max from pkl. Called once at FastAPI startup."""
        if not os.path.exists(self._model_path):
            logger.warning(
                "sentinel_if.pkl not found at %s — SL5 will return 0 pts. "
                "Run backend/app/ml/train_isolation_forest.py to generate the model.",
                self._model_path,
            )
            return
        try:
            import joblib  # type: ignore
            payload = joblib.load(self._model_path)
            self._model    = payload["model"]
            self._raw_min  = float(payload["raw_min"])
            self._raw_max  = float(payload["raw_max"])
            self._loaded   = True
            logger.info("IsolationForest model loaded from %s", self._model_path)
        except Exception as exc:
            logger.error("Failed to load IsolationForest model: %s", exc)
            self._loaded = False

    def score(self, validated_vitals: dict[str, Optional[float]]) -> SL5Result:
        """
        Extract 7-feature vector, normalise, run IF, return SL5Result.
        Falls back to 0 pts if model not loaded.
        """
        if not self._loaded or self._model is None:
            return SL5Result(
                anomaly_score=0.0,
                points_added=0.0,
                xai_label="Model not loaded",
                contributor=None,
            )

        FEATURE_KEYS = [
            "heart_rate", "respiratory_rate", "spo2",
            "body_temperature", "hrv_ms", "stress_score", "steps_per_hour",
        ]

        raw: dict[str, float] = {}
        substituted: list[str] = []
        for key in FEATURE_KEYS:
            val = validated_vitals.get(key)
            if val is None:
                raw[key] = _FEATURE_MEANS[key]
                substituted.append(key)
            else:
                raw[key] = val

        if substituted:
            logger.debug("IF: substituted population means for: %s", substituted)

        feature_vector = _normalise_features(raw)

        try:
            raw_score = self._model.decision_function([feature_vector])[0]
            # Normalise to 0–1; higher = more anomalous
            span = self._raw_max - self._raw_min
            if span == 0:
                anomaly_score = 0.0
            else:
                anomaly_score = float(1.0 - (raw_score - self._raw_min) / span)
                anomaly_score = max(0.0, min(1.0, anomaly_score))
        except Exception as exc:
            logger.error("IF scoring error: %s", exc)
            return SL5Result(
                anomaly_score=0.0,
                points_added=0.0,
                xai_label="Scoring error",
                contributor=None,
            )

        # Map anomaly_score to points
        if anomaly_score < IF_SCORE_LOW_THRESHOLD:
            points = 0.0
            label = ""
            contributor = None
        elif anomaly_score < IF_SCORE_MID_THRESHOLD:
            points = IF_POINTS_LOW
            label = "Mildly unusual vital combination"
            contributor = ScoreContributor(
                source="Isolation Forest (SL5)",
                layer="SL5",
                points=points,
                clinical_standard="Isolation Forest",
                detail=f"IF anomaly score {anomaly_score:.3f} — {label}",
            )
        elif anomaly_score < IF_SCORE_HIGH_THRESHOLD:
            points = IF_POINTS_MID
            label = "Anomalous vital fingerprint — deviates from baseline population"
            contributor = ScoreContributor(
                source="Isolation Forest (SL5)",
                layer="SL5",
                points=points,
                clinical_standard="Isolation Forest",
                detail=f"IF anomaly score {anomaly_score:.3f} — {label}",
            )
        else:
            points = IF_POINTS_HIGH
            label = "High-confidence anomaly — strongly atypical combination"
            contributor = ScoreContributor(
                source="Isolation Forest (SL5)",
                layer="SL5",
                points=points,
                clinical_standard="Isolation Forest",
                detail=f"IF anomaly score {anomaly_score:.3f} — {label}",
            )

        return SL5Result(
            anomaly_score=anomaly_score,
            points_added=points,
            xai_label=label,
            contributor=contributor,
        )

    @property
    def is_loaded(self) -> bool:
        return self._loaded
