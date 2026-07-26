from datetime import datetime, timezone
import os
import platform
import socket
import time
from typing import Literal
from uuid import uuid4

import psutil
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


STARTED_AT = time.time()
CULTURES: dict[str, dict[str, object]] = {}
JOBS: dict[str, dict[str, object]] = {}

app = FastAPI(
    title="Neuron Monitoring Service",
    description="Local REST interface for neuron monitoring workflows.",
    version="0.1.0",
)


@app.get("/", tags=["status"])
def root() -> dict[str, str]:
    return {
        "service": "neuron-monitoring-service",
        "status": "ok",
        "docs": "/docs",
        "health": "/health",
        "cultures": "/cultures",
        "culture_storage": "/cultures/storage",
        "overwatch": "/overwatch",
        "jobs": "/jobs",
    }


class CultureRegistration(BaseModel):
    ip_address: str = Field(..., description="Culture IP address or hostname.")
    port: int = Field(..., ge=1, le=65535, description="Culture REST API port.")


class CultureRegistrationResponse(BaseModel):
    id: str
    ip_address: str
    port: int
    registered_at: str
    status: str


class JobResponse(BaseModel):
    job_id: str
    section: Literal["cultures", "overwatch"]
    action: Literal["retrieve", "insert", "refill"]
    status: Literal["queued", "running", "completed", "failed"]
    created_at: str
    updated_at: str
    target_id: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_culture(culture_id: str) -> dict[str, object]:
    culture = CULTURES.get(culture_id)
    if culture is None:
        raise HTTPException(status_code=404, detail=f"Culture {culture_id} was not found")
    return culture


def _create_job(section: Literal["cultures", "overwatch"], action: Literal["retrieve", "insert", "refill"], target_id: str) -> dict[str, object]:
    now = _utc_now()
    job_id = str(uuid4())
    job = {
        "job_id": job_id,
        "section": section,
        "action": action,
        "status": "queued",
        "created_at": now,
        "updated_at": now,
        "target_id": target_id,
    }
    JOBS[job_id] = job
    return dict(job)


def _create_storage_job(culture_id: str, action: Literal["retrieve", "insert"]) -> dict[str, object]:
    _require_culture(culture_id)
    return _create_job("cultures", action, culture_id)


@app.get("/health", tags=["status"])
def health() -> dict[str, object]:
    disk = psutil.disk_usage("/")
    memory = psutil.virtual_memory()

    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "uptime_seconds": round(time.time() - STARTED_AT, 2),
        "system_uptime_seconds": round(time.time() - psutil.boot_time(), 2),
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "memory": {
            "total_mb": round(memory.total / 1024 / 1024, 2),
            "available_mb": round(memory.available / 1024 / 1024, 2),
            "used_percent": memory.percent,
        },
        "disk": {
            "total_gb": round(disk.total / 1024 / 1024 / 1024, 2),
            "free_gb": round(disk.free / 1024 / 1024 / 1024, 2),
            "used_percent": disk.percent,
        },
        "environment": os.getenv("APP_ENV", "local"),
    }


@app.get("/cultures", tags=["cultures"])
def list_cultures() -> dict[str, object]:
    return {
        "cultures": list(CULTURES.values()),
        "count": len(CULTURES),
    }


@app.post("/cultures/register", tags=["cultures"], response_model=CultureRegistrationResponse)
def register_culture(request: CultureRegistration) -> dict[str, object]:
    now = _utc_now()
    culture_id = str(uuid4())
    culture = {
        "id": culture_id,
        "ip_address": request.ip_address,
        "port": request.port,
        "registered_at": now,
        "status": "registered",
    }
    CULTURES[culture_id] = culture
    return dict(culture)


@app.get("/cultures/storage", tags=["cultures"])
def culture_storage() -> dict[str, object]:
    return {
        "status": "ok",
        "registered_cultures": len(CULTURES),
        "pending_jobs": sum(1 for job in JOBS.values() if job["section"] == "cultures" and job["status"] in ("queued", "running")),
    }


@app.post("/cultures/storage/retrieve/{id}", tags=["cultures"], response_model=JobResponse)
def retrieve_culture_from_storage(id: str) -> dict[str, object]:
    return _create_storage_job(id, "retrieve")


@app.post("/cultures/storage/insert/{id}", tags=["cultures"], response_model=JobResponse)
def insert_culture_into_storage(id: str) -> dict[str, object]:
    return _create_storage_job(id, "insert")


@app.get("/cultures/{id}/level", tags=["cultures"])
def culture_level(id: str) -> dict[str, object]:
    culture = _require_culture(id)
    return {
        "culture_id": id,
        "status": "not_implemented",
        "level": None,
        "source": {
            "ip_address": culture["ip_address"],
            "port": culture["port"],
        },
    }


@app.get("/overwatch/levels", tags=["overwatch"])
def overwatch_levels() -> dict[str, object]:
    levels = [
        {
            "culture_id": culture_id,
            "status": "not_implemented",
            "level": None,
            "source": {
                "ip_address": culture["ip_address"],
                "port": culture["port"],
            },
        }
        for culture_id, culture in CULTURES.items()
    ]
    return {
        "levels": levels,
        "count": len(levels),
    }


@app.post("/overwatch/refill/{id}", tags=["overwatch"], response_model=JobResponse)
def refill_culture(id: str) -> dict[str, object]:
    _require_culture(id)
    return _create_job("overwatch", "refill", id)


@app.get("/jobs", tags=["jobs"])
def list_jobs() -> dict[str, object]:
    return {
        "jobs": list(JOBS.values()),
        "count": len(JOBS),
    }
