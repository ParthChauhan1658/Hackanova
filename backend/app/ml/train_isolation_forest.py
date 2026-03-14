"""
One-time training script for the SENTINEL IsolationForest model.
Run before starting the server:
    python backend/app/ml/train_isolation_forest.py
Generates: backend/app/ml/sentinel_if.pkl
"""

from __future__ import annotations

import os
import sys

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest  # type: ignore

# ── Feature normalisation (mirrors IsolationForestWrapper._normalise_features) ─

def _normalise(hr, rr, spo2, temp, hrv, stress, steps):
    return [
        (hr   - 40.0)  / 160.0,
        (rr   - 6.0)   / 34.0,
        (spo2 - 80.0)  / 20.0,
        (temp - 34.0)  / 8.0,
        hrv   / 100.0,
        stress / 100.0,
        min(steps, 8000.0) / 8000.0,
    ]


if __name__ == "__main__":
    rng = np.random.default_rng(42)

    # ── Generate 2000 NORMAL rows ──────────────────────────────────────────────
    n = 2000
    hr_n     = np.clip(rng.normal(72,   8,   n), 55,  88)
    rr_n     = np.clip(rng.normal(15,   2,   n), 12,  18)
    spo2_n   = np.clip(rng.normal(97.5, 0.8, n), 95,  99)
    temp_n   = np.clip(rng.normal(36.8, 0.4, n), 36.1, 37.8)
    hrv_n    = np.clip(rng.normal(60,   12,  n), 45,  80)
    stress_n = np.clip(rng.normal(25,   10,  n), 10,  40)
    steps_n  = np.clip(rng.normal(2000, 800, n), 200, 5000)

    normal_features = np.array([
        _normalise(hr_n[i], rr_n[i], spo2_n[i], temp_n[i], hrv_n[i], stress_n[i], steps_n[i])
        for i in range(n)
    ])

    # Add Gaussian noise σ=0.02 after normalisation
    normal_features += rng.normal(0, 0.02, normal_features.shape)

    # ── Fit model ─────────────────────────────────────────────────────────────
    model = IsolationForest(
        contamination=0.05,
        n_estimators=100,
        random_state=42,
        max_samples="auto",
    )
    model.fit(normal_features)

    # ── Compute raw_min / raw_max from training set ────────────────────────────
    train_scores = model.decision_function(normal_features)
    raw_min = float(train_scores.min())
    raw_max = float(train_scores.max())

    # ── Validate on 200 ABNORMAL rows ─────────────────────────────────────────
    n_abn = 200
    abnormal_features = np.array([
        _normalise(115, 26, 91, 39.2, 22, 85, 0)
        for _ in range(n_abn)
    ])
    # Add small jitter so rows are not identical
    abnormal_features += rng.normal(0, 0.01, abnormal_features.shape)

    abn_raw = model.decision_function(abnormal_features)
    span = raw_max - raw_min
    if span == 0:
        abn_anomaly = np.zeros(n_abn)
    else:
        abn_anomaly = 1.0 - (abn_raw - raw_min) / span
        abn_anomaly = np.clip(abn_anomaly, 0.0, 1.0)

    passed = int((abn_anomaly > 0.7).sum())
    if passed < n_abn:
        print(
            f"WARNING: Only {passed}/{n_abn} abnormal rows scored > 0.7. "
            "Model may need re-tuning, but saving anyway."
        )
    else:
        print(f"Validation passed: {passed}/{n_abn} abnormal rows scored > 0.7")

    # ── Serialise ─────────────────────────────────────────────────────────────
    out_path = os.path.join(os.path.dirname(__file__), "sentinel_if.pkl")
    joblib.dump({"model": model, "raw_min": raw_min, "raw_max": raw_max}, out_path)
    print(f"Model trained. Saved to {out_path}")
    print(f"  raw_min={raw_min:.4f}  raw_max={raw_max:.4f}")
