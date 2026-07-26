from datetime import datetime, timezone
import os
import platform
import socket
import time

import psutil
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from app.camera_controller import CameraController, CameraControllerError
from app.led_controller import LedController, LedControllerError


STARTED_AT = time.time()
CAMERA_CONTROLLER = CameraController()
LED_CONTROLLER = LedController()

app = FastAPI(
    title="Raspberry Pi Monitoring Service",
    description="REST interface for Raspberry Pi health checks, camera capture, and Trinkey NeoPixel control.",
    version="0.3.0",
)


class LedOnRequest(BaseModel):
    hue: float = Field(..., ge=0, le=360, description="HSV hue in degrees.")
    saturation: float = Field(..., ge=0, le=1, description="HSV saturation from 0.0 to 1.0.")
    value: float = Field(..., ge=0, le=1, description="HSV value from 0.0 to 1.0.")
    brightness: float = Field(..., ge=0, le=1, description="NeoPixel brightness from 0.0 to 1.0.")


class LedFlashRequest(LedOnRequest):
    duration_ms: int = Field(150, ge=10, le=5000, description="How long each flash stays on.")
    count: int = Field(1, ge=1, le=50, description="Number of flashes.")
    gap_ms: int = Field(100, ge=0, le=5000, description="Off time between flashes.")


@app.get("/", tags=["status"])
def root() -> dict[str, str]:
    return {
        "service": "rpi-monitoring-service",
        "status": "ok",
        "docs": "/docs",
        "health": "/health",
        "camera": "/camera",
    }


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
        "environment": os.getenv("APP_ENV", "production"),
    }


@app.get("/camera", tags=["camera"])
def camera_status() -> dict[str, object]:
    return CAMERA_CONTROLLER.status()


@app.get("/camera/image", tags=["camera"])
def camera_image(
    width: int = 1280,
    height: int = 720,
    quality: int = 90,
    timeout_ms: int = 1000,
    hflip: bool = False,
    vflip: bool = False,
) -> FileResponse:
    if not 64 <= width <= 9152:
        raise HTTPException(status_code=422, detail="width must be between 64 and 9152")
    if not 64 <= height <= 6944:
        raise HTTPException(status_code=422, detail="height must be between 64 and 6944")
    if not 1 <= quality <= 100:
        raise HTTPException(status_code=422, detail="quality must be between 1 and 100")
    if not 0 <= timeout_ms <= 10000:
        raise HTTPException(status_code=422, detail="timeout_ms must be between 0 and 10000")

    try:
        image_path = CAMERA_CONTROLLER.capture_jpeg(
            width=width,
            height=height,
            quality=quality,
            timeout_ms=timeout_ms,
            hflip=hflip,
            vflip=vflip,
        )
    except CameraControllerError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return FileResponse(
        image_path,
        media_type="image/jpeg",
        filename="camera.jpg",
        background=BackgroundTask(image_path.unlink, missing_ok=True),
    )


@app.get("/led", tags=["led"])
def led_status() -> dict[str, object]:
    return LED_CONTROLLER.status()


@app.post("/led/on", tags=["led"])
def led_on(request: LedOnRequest) -> dict[str, object]:
    try:
        response = LED_CONTROLLER.turn_on(
            hue=request.hue,
            saturation=request.saturation,
            value=request.value,
            brightness=request.brightness,
        )
    except LedControllerError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "status": "ok",
        "led": "on",
        "trinkey": response,
    }


@app.post("/led/off", tags=["led"])
def led_off() -> dict[str, object]:
    try:
        response = LED_CONTROLLER.turn_off()
    except LedControllerError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "status": "ok",
        "led": "off",
        "trinkey": response,
    }


@app.post("/led/flash", tags=["led"])
def led_flash(request: LedFlashRequest) -> dict[str, object]:
    try:
        response = LED_CONTROLLER.flash(
            hue=request.hue,
            saturation=request.saturation,
            value=request.value,
            brightness=request.brightness,
            duration_ms=request.duration_ms,
            count=request.count,
            gap_ms=request.gap_ms,
        )
    except LedControllerError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "status": "ok",
        "led": "flashed",
        "trinkey": response,
    }
