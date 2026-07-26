from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app


IMAGE_DIRECTORY = Path(os.getenv("LIQUID_DEMO_IMAGE_DIR", "/Users/sai/Downloads"))
FULL_IMAGE = IMAGE_DIRECTORY / "camera-4.jpg"
LOW_IMAGE = IMAGE_DIRECTORY / "camera-6.jpg"

pytestmark = pytest.mark.skipif(
    not FULL_IMAGE.exists() or not LOW_IMAGE.exists(),
    reason="Set LIQUID_DEMO_IMAGE_DIR to the directory containing camera-4.jpg and camera-6.jpg",
)

client = TestClient(app)


def post_image(image_path: Path):
    return client.post(
        "/liquid/level",
        content=image_path.read_bytes(),
        headers={"content-type": "image/jpeg"},
    )


def test_full_reference_image_is_ok() -> None:
    response = post_image(FULL_IMAGE)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["percent_full"] >= 95
    assert payload["media_requested"] is None


def test_low_image_requests_one_ml_of_media() -> None:
    response = post_image(LOW_IMAGE)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "media_requested"
    assert payload["percent_full"] < 50
    assert payload["media_requested"] == "1 mL"


def test_invalid_image_is_rejected() -> None:
    response = client.post(
        "/liquid/level",
        content=b"not an image",
        headers={"content-type": "image/jpeg"},
    )

    assert response.status_code == 422


@pytest.mark.parametrize("body", [b"", b"ignored request contents"])
def test_trigger_workflow_always_requests_one_ml(body: bytes) -> None:
    response = client.post("/trigger_workflow", content=body)

    assert response.status_code == 200
    assert response.json() == {
        "status": "media_requested",
        "media_requested": "1 mL",
    }
