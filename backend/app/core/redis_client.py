"""
Async Redis wrapper — singleton connection pool with in-memory event buffer
for graceful reconnect.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import redis.asyncio as aioredis

from app.core.constants import REDIS_WINDOW_SIZE

logger = logging.getLogger(__name__)

_BUFFER_MAX = 100


class RedisClient:
    """
    Thin async wrapper around redis.asyncio.
    Accepts an optional pre-built client for testing (e.g. fakeredis).
    """

    def __init__(
        self,
        url: str = "redis://localhost:6379/0",
        client: Optional[aioredis.Redis] = None,
    ) -> None:
        self._url = url
        self._client: Optional[aioredis.Redis] = client
        self._connected: bool = client is not None  # pre-injected → treat as connected
        self._event_buffer: list[tuple[str, dict]] = []

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        if self._client is None:
            self._client = aioredis.from_url(self._url, decode_responses=True)
        try:
            await self._client.ping()
            self._connected = True
            logger.info("Redis connected")
            await self._flush_buffer()
        except aioredis.RedisError as exc:
            logger.error("Redis connect failed: %s", exc)
            self._connected = False

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()
        self._connected = False

    async def get_client(self) -> aioredis.Redis:
        return self._client  # type: ignore[return-value]

    # ── Sliding window ────────────────────────────────────────────────────────

    async def push_to_window(
        self,
        patient_id: str,
        vital_name: str,
        value: float,
        maxlen: int = REDIS_WINDOW_SIZE,
    ) -> None:
        key = f"vitals:{patient_id}:{vital_name}:window"
        try:
            await self._client.rpush(key, str(value))   # type: ignore
            await self._client.ltrim(key, -maxlen, -1)  # type: ignore
        except aioredis.RedisError as exc:
            logger.warning("push_to_window failed [%s/%s]: %s", patient_id, vital_name, exc)

    async def get_window(self, patient_id: str, vital_name: str) -> list[float]:
        key = f"vitals:{patient_id}:{vital_name}:window"
        try:
            raw: list[str] = await self._client.lrange(key, 0, -1)  # type: ignore
            return [float(v) for v in raw]
        except aioredis.RedisError as exc:
            logger.warning("get_window failed [%s/%s]: %s", patient_id, vital_name, exc)
            return []

    # ── Last-valid interpolation helpers ─────────────────────────────────────

    async def get_last_valid(self, patient_id: str, vital_name: str) -> Optional[float]:
        key = f"vitals:{patient_id}:last_valid:{vital_name}"
        try:
            val: Optional[str] = await self._client.get(key)  # type: ignore
            return float(val) if val is not None else None
        except aioredis.RedisError as exc:
            logger.warning("get_last_valid failed [%s/%s]: %s", patient_id, vital_name, exc)
            return None

    async def set_last_valid(self, patient_id: str, vital_name: str, value: float) -> None:
        key = f"vitals:{patient_id}:last_valid:{vital_name}"
        try:
            await self._client.set(key, str(value))  # type: ignore
        except aioredis.RedisError as exc:
            logger.warning("set_last_valid failed [%s/%s]: %s", patient_id, vital_name, exc)

    # ── HRV session baseline (exponential running mean) ──────────────────────

    async def get_session_hrv_baseline(
        self, patient_id: str, session_id: str
    ) -> Optional[float]:
        key = f"session:{patient_id}:{session_id}:hrv_baseline"
        try:
            val: Optional[str] = await self._client.get(key)  # type: ignore
            return float(val) if val is not None else None
        except aioredis.RedisError as exc:
            logger.warning("get_session_hrv_baseline failed: %s", exc)
            return None

    async def update_session_hrv_baseline(
        self, patient_id: str, session_id: str, hrv_value: float
    ) -> None:
        key = f"session:{patient_id}:{session_id}:hrv_baseline"
        try:
            existing = await self.get_session_hrv_baseline(patient_id, session_id)
            if existing is None:
                new_baseline = hrv_value
            else:
                alpha = 0.1  # exponential moving average
                new_baseline = alpha * hrv_value + (1.0 - alpha) * existing
            await self._client.set(key, str(new_baseline))  # type: ignore
        except aioredis.RedisError as exc:
            logger.warning("update_session_hrv_baseline failed: %s", exc)

    # ── Pub/Sub ───────────────────────────────────────────────────────────────

    async def publish_event(self, channel: str, payload: dict) -> None:
        try:
            if self._connected and self._client:
                await self._client.publish(channel, json.dumps(payload, default=str))
                if self._event_buffer:
                    await self._flush_buffer()
            else:
                self._buffer_event(channel, payload)
        except aioredis.RedisError as exc:
            logger.warning("publish_event failed, buffering: %s", exc)
            self._buffer_event(channel, payload)

    def _buffer_event(self, channel: str, payload: dict) -> None:
        if len(self._event_buffer) < _BUFFER_MAX:
            self._event_buffer.append((channel, payload))
        else:
            logger.warning("Event buffer full — dropping event on channel %s", channel)

    async def _flush_buffer(self) -> None:
        if not self._event_buffer or not self._client:
            return
        flushed = 0
        while self._event_buffer:
            channel, payload = self._event_buffer[0]
            try:
                await self._client.publish(channel, json.dumps(payload, default=str))
                self._event_buffer.pop(0)
                flushed += 1
            except aioredis.RedisError:
                break
        if flushed:
            logger.info("Flushed %d buffered events to Redis", flushed)


# Module-level singleton — override in tests via dependency injection
redis_client = RedisClient()
