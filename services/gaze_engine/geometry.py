"""Validation and scope rules for durable GeometrySnapshot v2 records."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC
from typing import Any

from services.gaze_engine.adapter import GazeNormalizationError
from services.gaze_engine.context import utc_timestamp


@dataclass(frozen=True)
class GeometryScope:
    """Server-resolved session/study/AOI scope for a geometry snapshot.

    This value is a trusted handoff from an upstream authorization/configuration
    service. It is not constructed from browser input by this module.
    """

    session_id: str
    study_id: str
    aoi_set_version: str

    def __post_init__(self) -> None:
        for field in ("session_id", "study_id", "aoi_set_version"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value:
                raise GazeNormalizationError(f"geometry scope {field} must be non-empty")


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise GazeNormalizationError(f"geometry {field} must be finite")
    return float(value)


def validate_geometry_snapshot(
    snapshot: dict[str, Any], *, scope: GeometryScope
) -> dict[str, Any]:
    """Validate a v2 snapshot and return a copy with normalized timestamps.

    The v2 contract is deliberately strict here because a study-scoped durable
    store must not accept the legacy v1 snapshot, which has no study identity.
    Browser provenance is retained by the repository, outside the frozen JSON
    contract, and does not make the geometry authoritative by itself.
    """

    required = {
        "schema_version", "snapshot_id", "session_id", "study_id", "captured_at",
        "aoi_set_version", "viewport_width_px", "viewport_height_px", "scroll_x_px",
        "scroll_y_px", "zoom", "rectangles",
    }
    if not isinstance(snapshot, dict) or set(snapshot) != required:
        raise GazeNormalizationError("geometry snapshot must match the v2 fields")
    if snapshot["schema_version"] != "2.0.0":
        raise GazeNormalizationError("only GeometrySnapshot v2 is durable for study-scoped use")
    for field in ("snapshot_id", "session_id", "study_id", "aoi_set_version"):
        if not isinstance(snapshot[field], str) or not snapshot[field]:
            raise GazeNormalizationError(f"geometry {field} must be non-empty")
    if (
        snapshot["session_id"], snapshot["study_id"], snapshot["aoi_set_version"]
    ) != (scope.session_id, scope.study_id, scope.aoi_set_version):
        raise GazeNormalizationError("geometry snapshot scope does not match trusted scope")
    captured_at = utc_timestamp(snapshot["captured_at"], "geometry captured_at")
    width = _finite_number(snapshot["viewport_width_px"], "viewport_width_px")
    height = _finite_number(snapshot["viewport_height_px"], "viewport_height_px")
    scroll_x = _finite_number(snapshot["scroll_x_px"], "scroll_x_px")
    scroll_y = _finite_number(snapshot["scroll_y_px"], "scroll_y_px")
    zoom = _finite_number(snapshot["zoom"], "zoom")
    if width <= 0 or height <= 0 or scroll_x < 0 or scroll_y < 0 or zoom <= 0:
        raise GazeNormalizationError("geometry viewport, scroll, or zoom values are out of range")
    rectangles = snapshot["rectangles"]
    if not isinstance(rectangles, list):
        raise GazeNormalizationError("geometry rectangles must be an array")
    seen_aoi_ids: set[str] = set()
    normalized_rectangles: list[dict[str, Any]] = []
    rectangle_fields = {"aoi_id", "left_px", "top_px", "right_px", "bottom_px", "priority"}
    for rectangle in rectangles:
        if not isinstance(rectangle, dict) or set(rectangle) != rectangle_fields:
            raise GazeNormalizationError("geometry rectangle has invalid fields")
        aoi_id = rectangle["aoi_id"]
        if not isinstance(aoi_id, str) or not aoi_id or aoi_id in seen_aoi_ids:
            raise GazeNormalizationError("geometry rectangle AOI identity is invalid or duplicated")
        priority = rectangle["priority"]
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise GazeNormalizationError("geometry rectangle priority must be an integer")
        left = _finite_number(rectangle["left_px"], "left_px")
        top = _finite_number(rectangle["top_px"], "top_px")
        right = _finite_number(rectangle["right_px"], "right_px")
        bottom = _finite_number(rectangle["bottom_px"], "bottom_px")
        if right <= left or bottom <= top:
            raise GazeNormalizationError("geometry rectangle bounds are invalid")
        seen_aoi_ids.add(aoi_id)
        normalized_rectangles.append(
            {
                "aoi_id": aoi_id,
                "left_px": left,
                "top_px": top,
                "right_px": right,
                "bottom_px": bottom,
                "priority": priority,
            }
        )
    return {
        **snapshot,
        "captured_at": captured_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "viewport_width_px": width,
        "viewport_height_px": height,
        "scroll_x_px": scroll_x,
        "scroll_y_px": scroll_y,
        "zoom": zoom,
        "rectangles": normalized_rectangles,
    }
