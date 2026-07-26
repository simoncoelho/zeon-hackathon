from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

import cv2
import numpy as np


DEFAULT_FULL_DEPTH_RATIO = 0.291015625


class LiquidLevelControllerError(RuntimeError):
    pass


@dataclass(frozen=True)
class LiquidLevelReading:
    percent_full: float
    confidence: float
    liquid_surface_y: int
    vial_top_y: int
    vial_bottom_y: int


class LiquidLevelController:
    """Estimate vial fullness from a fixed, front-facing camera image.

    The detector finds the vial's vertical edges, cap boundary, liquid boundary,
    and bottom boundary. It uses ratios instead of raw pixels so small framing
    changes do not directly change the reported percentage.
    """

    def __init__(self) -> None:
        self.full_depth_ratio = self._read_float(
            "LIQUID_FULL_DEPTH_RATIO",
            DEFAULT_FULL_DEPTH_RATIO,
            minimum=0.01,
            maximum=1.0,
        )
        self.request_threshold_percent = self._read_float(
            "LIQUID_REQUEST_THRESHOLD_PERCENT",
            50.0,
            minimum=0.0,
            maximum=100.0,
        )
        self.request_amount = os.getenv("LIQUID_REQUEST_AMOUNT", "1 mL")

    def estimate_bytes(self, image_bytes: bytes) -> LiquidLevelReading:
        if not image_bytes:
            raise LiquidLevelControllerError("The uploaded image is empty")

        encoded = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if image is None:
            raise LiquidLevelControllerError("OpenCV could not decode the uploaded image")
        return self.estimate(image)

    def estimate_path(self, image_path: Path) -> LiquidLevelReading:
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            raise LiquidLevelControllerError(f"OpenCV could not decode {image_path}")
        return self.estimate(image)

    def estimate(self, image: np.ndarray) -> LiquidLevelReading:
        if image.ndim != 3 or image.shape[2] != 3:
            raise LiquidLevelControllerError("Expected a three-channel BGR image")

        height, width = image.shape[:2]
        if width < 320 or height < 240:
            raise LiquidLevelControllerError("Image must be at least 320x240 pixels")

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)

        left_x, right_x, side_confidence = self._find_vial_sides(blurred)
        vial_width = right_x - left_x
        center_left = int(left_x + 0.25 * vial_width)
        center_right = int(right_x - 0.25 * vial_width)

        row_mean = blurred[:, center_left:center_right].astype(np.float32).mean(axis=1)
        smoothed_rows = np.convolve(row_mean, np.ones(9, dtype=np.float32) / 9, mode="same")
        row_edges = np.abs(np.diff(smoothed_rows))

        top_start = int(0.03 * height)
        top_end = int(0.45 * height)
        vial_top = top_start + int(np.argmax(row_edges[top_start:top_end]))

        surface_start = int(vial_top + 0.45 * (height - vial_top))
        surface_end = int(vial_top + 0.80 * (height - vial_top))
        if surface_end <= surface_start:
            raise LiquidLevelControllerError("Could not construct a liquid search region")

        surface_window = row_edges[surface_start:surface_end]
        surface_offset = int(np.argmax(surface_window))
        liquid_surface = surface_start + surface_offset
        surface_peak = float(surface_window[surface_offset])
        surface_baseline = float(np.percentile(surface_window, 90))
        surface_prominence = surface_peak / max(surface_baseline, 0.001)

        vial_bottom = self._find_vial_bottom(
            blurred=blurred,
            left_x=left_x,
            right_x=right_x,
            liquid_surface=liquid_surface,
            vial_top=vial_top,
        )
        if not vial_top < liquid_surface < vial_bottom:
            raise LiquidLevelControllerError("Detected vial geometry is inconsistent")

        detected_depth_ratio = (vial_bottom - liquid_surface) / (vial_bottom - vial_top)
        percent_full = float(np.clip(100 * detected_depth_ratio / self.full_depth_ratio, 0, 100))

        prominence_confidence = float(np.clip((surface_prominence - 1.0) / 2.0, 0, 1))
        confidence = round(0.55 * side_confidence + 0.45 * prominence_confidence, 3)

        return LiquidLevelReading(
            percent_full=round(percent_full, 1),
            confidence=confidence,
            liquid_surface_y=liquid_surface,
            vial_top_y=vial_top,
            vial_bottom_y=vial_bottom,
        )

    def response_for(self, reading: LiquidLevelReading) -> dict[str, object]:
        needs_media = reading.percent_full < self.request_threshold_percent
        return {
            "status": "media_requested" if needs_media else "ok",
            "percent_full": reading.percent_full,
            "media_requested": self.request_amount if needs_media else None,
            "confidence": reading.confidence,
        }

    def _find_vial_sides(self, blurred: np.ndarray) -> tuple[int, int, float]:
        height, width = blurred.shape
        gradient_x = np.abs(cv2.Sobel(blurred, cv2.CV_32F, 1, 0, ksize=3))
        vertical_band = gradient_x[int(0.10 * height) : int(0.85 * height)]
        column_strength = np.percentile(vertical_band, 75, axis=0)

        left_start, left_end = int(0.25 * width), int(0.48 * width)
        right_start, right_end = int(0.58 * width), int(0.85 * width)
        left_x = left_start + int(np.argmax(column_strength[left_start:left_end]))
        right_x = right_start + int(np.argmax(column_strength[right_start:right_end]))

        vial_width = right_x - left_x
        if vial_width < 0.25 * width:
            raise LiquidLevelControllerError("Could not find both sides of the vial")

        search_baseline = float(np.median(column_strength[left_start:right_end]))
        side_peak = min(float(column_strength[left_x]), float(column_strength[right_x]))
        side_confidence = float(np.clip((side_peak / max(search_baseline, 1.0) - 1.0) / 5.0, 0, 1))
        return left_x, right_x, side_confidence

    def _find_vial_bottom(
        self,
        blurred: np.ndarray,
        left_x: int,
        right_x: int,
        liquid_surface: int,
        vial_top: int,
    ) -> int:
        height = blurred.shape[0]
        vial_width = right_x - left_x
        edges = cv2.Canny(blurred, 40, 120)
        lines = cv2.HoughLinesP(
            edges,
            1,
            np.pi / 180,
            threshold=25,
            minLineLength=max(40, int(0.25 * vial_width)),
            maxLineGap=25,
        )

        candidates: list[float] = []
        if lines is not None:
            for x1, y1, x2, y2 in np.asarray(lines).reshape(-1, 4):
                delta_x = int(x2) - int(x1)
                delta_y = int(y2) - int(y1)
                angle = abs(float(np.degrees(np.arctan2(delta_y, delta_x))))
                line_y = (int(y1) + int(y2)) / 2
                overlap = max(
                    0,
                    min(max(int(x1), int(x2)), right_x) - max(min(int(x1), int(x2)), left_x),
                )

                if (
                    angle <= 8
                    and line_y > liquid_surface + 0.04 * (height - vial_top)
                    and overlap >= 0.22 * vial_width
                ):
                    candidates.append(line_y)

        # A vial cropped by the bottom of the frame has no visible bottom edge.
        # In that case, the last image row is the best available bottom boundary.
        return int(max(candidates, default=height - 1))

    @staticmethod
    def _read_float(name: str, default: float, minimum: float, maximum: float) -> float:
        raw_value = os.getenv(name)
        if raw_value is None:
            return default
        try:
            value = float(raw_value)
        except ValueError as exc:
            raise LiquidLevelControllerError(f"{name} must be a number") from exc
        if not minimum <= value <= maximum:
            raise LiquidLevelControllerError(f"{name} must be between {minimum} and {maximum}")
        return value
