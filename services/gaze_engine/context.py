"""Validated study/trial observation context for gaze processing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from services.gaze_engine.adapter import GazeNormalizationError
from services.gaze_engine.quality import evaluate_gaze_quality
from services.telemetry.ingestion import _parse_utc_timestamp


def utc_timestamp(value: Any, field: str) -> datetime:
    try:
        return _parse_utc_timestamp(value)
    except (TypeError, ValueError) as exc:
        raise GazeNormalizationError(f"{field} must be a valid UTC timestamp") from exc


@dataclass(frozen=True)
class TrialObservationContext:
    """The only context accepted by production trial-scoped gaze processing.

    The interval is start-inclusive and end-exclusive.  Its identity is
    study-scoped, so the same trial_id in another study cannot be mixed in.
    """

    session_id: str
    study_id: str
    trial_id: str
    aoi_set_version: str
    window_start: str
    window_end: str

    def __post_init__(self) -> None:
        for name in ("session_id", "study_id", "trial_id", "aoi_set_version"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise GazeNormalizationError(f"{name} must be a non-empty string")
        start = utc_timestamp(self.window_start, "window_start")
        end = utc_timestamp(self.window_end, "window_end")
        if end <= start:
            raise GazeNormalizationError("window_end must be after window_start")

    @property
    def start(self) -> datetime:
        return utc_timestamp(self.window_start, "window_start")

    @property
    def end(self) -> datetime:
        return utc_timestamp(self.window_end, "window_end")


def validate_observation_association(association: dict[str, Any]) -> tuple[TrialObservationContext, list[dict[str, Any]]]:
    """Validate the versioned association and reject out-of-window samples."""

    if not isinstance(association, dict) or association.get("schema_version") != "1.0.0":
        raise GazeNormalizationError("unsupported gaze observation association")
    required = {"schema_version", "association_id", "session_id", "study_id", "trial_id", "aoi_set_version", "window_start", "window_end", "gaze_records"}
    if set(association) != required:
        raise GazeNormalizationError("gaze observation association has invalid fields")
    if not all(isinstance(association[field], str) and association[field] for field in required - {"schema_version", "gaze_records"}):
        raise GazeNormalizationError("gaze observation association string fields are invalid")
    if not isinstance(association["gaze_records"], list):
        raise GazeNormalizationError("gaze observation association is missing required fields")
    context = TrialObservationContext(
        session_id=association["session_id"],
        study_id=association["study_id"],
        trial_id=association["trial_id"],
        aoi_set_version=association["aoi_set_version"],
        window_start=association["window_start"],
        window_end=association["window_end"],
    )
    records = association["gaze_records"]
    evaluate_gaze_quality(records)
    seen: set[str] = set()
    for record in records:
        if record["sample_id"] in seen:
            raise GazeNormalizationError(f"duplicate sample_id: {record['sample_id']!r}")
        seen.add(record["sample_id"])
        if record["session_id"] != context.session_id:
            raise GazeNormalizationError("gaze record session_id does not match observation context")
        occurred = utc_timestamp(record["occurred_at"], "gaze_record.occurred_at")
        if not context.start <= occurred < context.end:
            raise GazeNormalizationError("gaze record occurred_at is outside the observation window")
    return context, records
