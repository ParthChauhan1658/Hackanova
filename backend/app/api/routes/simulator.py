"""
Simulator control routes.
POST /api/v1/simulator/start
POST /api/v1/simulator/stop
GET  /api/v1/simulator/status/{patient_id}
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.services.simulator import SimulatorAlreadyRunning

logger = logging.getLogger(__name__)
router = APIRouter()

# Resolve relative to this file so it works regardless of CWD
# __file__ = backend/app/api/routes/simulator.py → go up 4 levels to get backend/
_DEFAULT_DATA_DIR = str(Path(__file__).resolve().parent.parent.parent.parent / "data" / "synthetic")


class SimulatorStartRequest(BaseModel):
    patient_id: str
    csv_file: str           # filename only — resolved against CSV_DATA_DIR
    interval_seconds: float = 0.5
    loop: bool = True


class SimulatorStopRequest(BaseModel):
    patient_id: str


@router.post("/api/v1/simulator/start")
async def start_simulator(req: SimulatorStartRequest, request: Request):
    simulator = request.app.state.simulator
    pipeline  = request.app.state.pipeline

    data_dir = Path(os.getenv("CSV_DATA_DIR", _DEFAULT_DATA_DIR)).resolve()
    csv_path = (data_dir / req.csv_file).resolve()

    # Path traversal protection
    if not str(csv_path).startswith(str(data_dir)):
        raise HTTPException(status_code=400, detail="Invalid csv_file: path traversal rejected")

    if not csv_path.exists():
        raise HTTPException(status_code=404, detail=f"CSV file not found: {req.csv_file}")

    try:
        await simulator.start(
            patient_id=req.patient_id,
            csv_path=str(csv_path),
            on_reading=pipeline.process,
            interval_seconds=req.interval_seconds,
            loop=req.loop,
        )
    except SimulatorAlreadyRunning as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return {
        "status":     "started",
        "patient_id": req.patient_id,
        "csv_file":   req.csv_file,
    }


@router.post("/api/v1/simulator/stop")
async def stop_simulator(req: SimulatorStopRequest, request: Request):
    await request.app.state.simulator.stop(req.patient_id)
    return {"status": "stopped", "patient_id": req.patient_id}


@router.get("/api/v1/simulator/status/{patient_id}")
async def simulator_status(patient_id: str, request: Request):
    stats = request.app.state.simulator.get_stats(patient_id)
    if stats is None:
        raise HTTPException(
            status_code=404,
            detail=f"No simulator found for patient '{patient_id}'",
        )
    return stats
