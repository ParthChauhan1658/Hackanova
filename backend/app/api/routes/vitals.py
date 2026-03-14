"""
REST + WebSocket routes for vital sign ingestion and fall acknowledgement.
POST /api/v1/vitals/ingest              — single reading, fall events processed inline
POST /api/v1/fall/{patient_id}/acknowledge — acknowledge an active confirmed fall
WS   /ws/vitals/{patient_id}            — streaming ingestion with 30 s heartbeat watchdog
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, WebSocket, WebSocketDisconnect

from app.models.vitals import FallEvent, VitalReading

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/v1/vitals/ingest")
async def ingest_vital(
    reading: VitalReading,
    background_tasks: BackgroundTasks,
    request: Request,
):
    """
    Accept a single VitalReading.
    All readings (including fall events) are processed as background tasks
    so the HTTP response returns immediately.
    """
    pipeline = request.app.state.pipeline
    background_tasks.add_task(pipeline.process, reading)

    return {
        "status":     "accepted",
        "reading_id": reading.reading_id,
        "patient_id": reading.patient_id,
        "timestamp":  reading.timestamp.isoformat(),
    }


@router.get("/api/v1/vitals/latest/{patient_id}")
async def get_latest_vitals(patient_id: str, request: Request):
    """
    Return the most recent raw VitalReading for a patient (cached in Redis, 30 s TTL).
    Includes latitude/longitude from the CSV wearable data.
    """
    redis = request.app.state.redis_client
    client = await redis.get_client()
    raw = await client.get(f"sentinel:vitals:{patient_id}:latest")
    if not raw:
        raise HTTPException(
            status_code=404,
            detail=f"No recent vitals cached for patient '{patient_id}' — simulator may not be running",
        )
    return json.loads(raw)


@router.post("/api/v1/fall/{patient_id}/acknowledge")
async def acknowledge_fall(patient_id: str, request: Request):
    """
    Acknowledge an active confirmed fall for a patient.
    Stops the EMS countdown if the fall has been confirmed but not yet dispatched.
    Returns 200 if acknowledged, 404 if no active confirmed fall exists.
    """
    fall_protocol = getattr(request.app.state, "fall_protocol", None)
    if fall_protocol is None:
        raise HTTPException(status_code=503, detail="Fall protocol not initialised")

    acknowledged = await fall_protocol.acknowledge(patient_id)
    if not acknowledged:
        raise HTTPException(
            status_code=404,
            detail=f"No active confirmed fall found for patient {patient_id}",
        )
    return {"status": "acknowledged", "patient_id": patient_id}


@router.websocket("/ws/vitals/{patient_id}")
async def vitals_websocket(websocket: WebSocket, patient_id: str):
    """
    Streaming ingestion WebSocket.
    Heartbeat watchdog: no frame for 30 s → publish WEARABLE_DISCONNECTED and close.
    """
    await websocket.accept()
    pipeline = websocket.app.state.pipeline
    redis    = websocket.app.state.redis_client

    try:
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_json(), timeout=30.0
                )
            except asyncio.TimeoutError:
                logger.warning("[%s] WebSocket heartbeat timeout — disconnecting", patient_id)
                await redis.publish_event(
                    f"actions:{patient_id}",
                    {"event": "WEARABLE_DISCONNECTED", "patient_id": patient_id},
                )
                await websocket.close()
                break

            try:
                reading = VitalReading.model_validate(data)
                await pipeline.process(reading)
            except Exception as exc:
                await websocket.send_json(
                    {"error": "invalid_reading", "detail": str(exc)}
                )

    except WebSocketDisconnect:
        logger.info("[%s] WebSocket client disconnected", patient_id)
