"""
DataSimulator — CSV replay engine.
Reads the 28-column synthetic dataset and streams VitalReading objects
at a configurable interval via asyncio tasks.
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Optional

import pandas as pd

from app.core.constants import SIMULATOR_DEFAULT_INTERVAL_SECONDS
from app.core.redis_client import RedisClient
from app.models.vitals import ActivityLevel, ECGRhythm, FallEvent, VitalReading

logger = logging.getLogger(__name__)


# ── Exceptions ────────────────────────────────────────────────────────────────

class SimulatorAlreadyRunning(Exception):
    def __init__(self, patient_id: str) -> None:
        super().__init__(f"Simulator already running for patient '{patient_id}'")
        self.patient_id = patient_id


# ── Stats dataclass ───────────────────────────────────────────────────────────

@dataclass
class SimulatorStats:
    patient_id: str
    ticks_sent: int = 0
    elapsed_seconds: float = 0.0
    current_row_index: int = 0
    total_rows: int = 0
    is_running: bool = False


# ── ECG rhythm mapping (dataset values → ECGRhythm enum) ─────────────────────
_ECG_MAP: dict[str, str] = {
    "NORMAL_SINUS": "NORMAL",
    "NORMAL":       "NORMAL",
    "AFIB":         "AFIB",
    "VT":           "VT",
    "VF":           "VF",
    "TACHYCARDIA":  "UNKNOWN",
    "BRADYCARDIA":  "UNKNOWN",
    "STEMI_PATTERN":"UNKNOWN",
    "PVC":          "UNKNOWN",
    "UNKNOWN":      "UNKNOWN",
}

# Activity level mapping (dataset values → ActivityLevel enum)
_ACTIVITY_MAP: dict[str, str] = {
    "RESTING":   "RESTING",
    "SEDENTARY": "SEDENTARY",
    "LIGHT":     "RESTING",    # dataset uses LIGHT → closest enum value
    "ACTIVE":    "ACTIVE",
    "MODERATE":  "ACTIVE",     # dataset uses MODERATE → closest enum value
    "VIGOROUS":  "VIGOROUS",
}


# ── DataSimulator ─────────────────────────────────────────────────────────────

class DataSimulator:
    def __init__(self, redis_client: RedisClient) -> None:
        self._redis = redis_client
        self._tasks: dict[str, asyncio.Task] = {}
        self._stats: dict[str, SimulatorStats] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    async def start(
        self,
        patient_id: str,
        csv_path: str,
        on_reading: Callable[[VitalReading], Awaitable[None]],
        interval_seconds: float = SIMULATOR_DEFAULT_INTERVAL_SECONDS,
        loop: bool = True,
    ) -> None:
        if patient_id in self._tasks and not self._tasks[patient_id].done():
            raise SimulatorAlreadyRunning(patient_id)

        readings = self._load_csv(csv_path, patient_id)
        if not readings:
            logger.warning("[%s] No valid readings loaded from %s", patient_id, csv_path)
            return

        stats = SimulatorStats(
            patient_id=patient_id,
            total_rows=len(readings),
            is_running=True,
        )
        self._stats[patient_id] = stats

        task = asyncio.create_task(
            self._replay_loop(patient_id, readings, on_reading, interval_seconds, loop, stats),
            name=f"simulator-{patient_id}",
        )
        self._tasks[patient_id] = task
        logger.info(
            "[%s] Simulator started — %d rows, interval=%.2fs, loop=%s",
            patient_id, len(readings), interval_seconds, loop,
        )

    async def stop(self, patient_id: str) -> None:
        task = self._tasks.get(patient_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.pop(patient_id, None)
        if patient_id in self._stats:
            self._stats[patient_id].is_running = False
        logger.info("[%s] Simulator stopped", patient_id)

    def is_running(self, patient_id: str) -> bool:
        task = self._tasks.get(patient_id)
        return task is not None and not task.done()

    def active_patients(self) -> list[str]:
        return [pid for pid, task in self._tasks.items() if not task.done()]

    def get_stats(self, patient_id: str) -> Optional[SimulatorStats]:
        return self._stats.get(patient_id)

    # ── Internal replay loop ──────────────────────────────────────────────────

    async def _replay_loop(
        self,
        patient_id: str,
        readings: list[VitalReading],
        on_reading: Callable[[VitalReading], Awaitable[None]],
        interval_seconds: float,
        loop: bool,
        stats: SimulatorStats,
    ) -> None:
        start = asyncio.get_event_loop().time()
        idx = 0
        try:
            while True:
                if idx >= len(readings):
                    if loop:
                        idx = 0
                    else:
                        break

                reading = readings[idx]
                stats.current_row_index = idx

                try:
                    await on_reading(reading)
                except Exception as exc:
                    logger.error("[%s] Callback error at row %d: %s", patient_id, idx, exc)

                stats.ticks_sent += 1
                stats.elapsed_seconds = asyncio.get_event_loop().time() - start
                idx += 1

                await asyncio.sleep(interval_seconds)

        except asyncio.CancelledError:
            logger.info("[%s] Replay loop cancelled", patient_id)
        finally:
            stats.is_running = False
            if not loop:
                await self.stop(patient_id)

    # ── CSV loading ───────────────────────────────────────────────────────────

    def _load_csv(self, csv_path: str, patient_id: str) -> list[VitalReading]:
        try:
            df = pd.read_csv(csv_path)
        except Exception as exc:
            logger.error("[%s] Failed to read CSV %s: %s", patient_id, csv_path, exc)
            return []

        readings: list[VitalReading] = []
        for i, row in df.iterrows():
            try:
                data = self._map_row(row)
                data["patient_id"] = patient_id  # override CSV patient_id with simulator's
                reading = VitalReading.model_validate(data)
                readings.append(reading)
            except Exception as exc:
                logger.warning("[%s] Row %d parse error: %s", patient_id, i, exc)

        logger.info("[%s] Loaded %d / %d rows from %s", patient_id, len(readings), len(df), csv_path)
        return readings

    def _map_row(self, row) -> dict:
        """Map CSV column names → VitalReading internal field names."""

        def safe(val):
            if val is None:
                return None
            try:
                if isinstance(val, float) and math.isnan(val):
                    return None
            except TypeError:
                pass
            return val

        def safe_float(val) -> Optional[float]:
            v = safe(val)
            if v is None:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        def safe_bool(val) -> bool:
            v = safe(val)
            if v is None:
                return False
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.strip().lower() in ("true", "1", "yes")
            return bool(v)

        # ECG rhythm: map dataset values to ECGRhythm enum values
        raw_ecg = safe(row.get("ecg_rhythm"))
        ecg_rhythm = None
        if raw_ecg is not None:
            ecg_rhythm = _ECG_MAP.get(str(raw_ecg).strip().upper(), "UNKNOWN")

        # Activity level: map dataset values to ActivityLevel enum values
        raw_activity = safe(row.get("activity_level"))
        activity_context = None
        if raw_activity is not None:
            activity_context = _ACTIVITY_MAP.get(str(raw_activity).strip().upper(), "RESTING")

        # Fall event: default to NONE
        raw_fall = safe(row.get("fall_event"))
        fall_event = "NONE"
        if raw_fall is not None:
            fall_str = str(raw_fall).strip().upper()
            if fall_str in ("POSSIBLE_FALL", "CONFIRMED_FALL"):
                fall_event = fall_str

        return {
            "reading_id":          str(safe(row.get("reading_id")) or ""),
            "patient_id":          str(safe(row.get("patient_id")) or ""),
            "session_id":          str(safe(row.get("session_id")) or ""),
            "timestamp":           safe(row.get("timestamp")),
            # Vitals — internal names
            "heart_rate":          safe_float(row.get("heart_rate_bpm")),
            "respiratory_rate":    safe_float(row.get("respiratory_rate")),
            "spo2":                safe_float(row.get("spo2_percent")),
            "ecg_rhythm":          ecg_rhythm,
            "ecg_st_deviation_mm": safe_float(row.get("ecg_st_deviation_mm")),
            "ecg_qtc_ms":          safe_float(row.get("ecg_qtc_ms")),
            "body_temperature":    safe_float(row.get("temperature_celsius")),
            "sleep_efficiency":    safe_float(row.get("sleep_efficiency_pct")),
            "deep_sleep_pct":      safe_float(row.get("deep_sleep_pct")),
            "rem_pct":             safe_float(row.get("rem_pct")),
            "hrv_ms":              safe_float(row.get("hrv_rmssd_ms")),
            "stress_score":        safe_float(row.get("stress_score")),
            "fall_event":          fall_event,
            "steps_per_hour":      safe_float(row.get("steps_per_hour")),
            "activity_context":    activity_context,
            # Patient metadata
            "age":                 safe(row.get("age")),
            "gender":              safe(row.get("gender")),
            "weight_kg":           safe_float(row.get("weight_kg")),
            "has_chronic_condition": safe_bool(row.get("has_chronic_condition")),
            # Location
            "latitude":            safe_float(row.get("latitude")),
            "longitude":           safe_float(row.get("longitude")),
            "location_stale":      safe_bool(row.get("location_stale")),
            # Source
            "source":              str(safe(row.get("source")) or "synthetic_dataset"),
            "signal_quality":      safe_float(row.get("signal_quality_pct")),
        }
