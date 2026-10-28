"""Deterministic quality and calibration assessment for canonical GazeRecords."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from statistics import fmean
from typing import Any

from services.gaze_engine.adapter import DuplicateSampleIdentity, GazeNormalizationError
from services.telemetry.ingestion import _parse_utc_timestamp

MIN_VALID_SAMPLES = 3
MIN_VALID_FRACTION = 0.5
MIN_MEAN_CONFIDENCE = 0.5
USABLE_UNVERIFIED = "usable_unverified"
CALIBRATION_STATUSES = {"pending", "passed", "failed", "not_required", "low_quality"}


@dataclass(frozen=True)
class GazeQualityAssessment:
    """Internal quality result; not a replacement for a versioned schema."""

    quality_status: str
    calibration_status: str
    sample_count: int
    valid_sample_count: int
    valid_fraction: float
    mean_confidence: float | None
    quality_flags: tuple[str, ...]
    missingness: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise GazeNormalizationError(f"{field} must be a finite number")
    return float(value)


def _validate_record(record: dict[str, Any]) -> None:
    if not isinstance(record, dict):
        raise GazeNormalizationError("gaze record must be an object")
    required = {
        "schema_version",
        "sample_id",
        "session_id",
        "occurred_at",
        "coordinate_space",
        "x_normalized",
        "y_normalized",
        "confidence",
        "valid",
        "calibration_status",
        "quality_flags",
    }
    missing = sorted(required - record.keys())
    if missing:
        raise GazeNormalizationError(f"gaze record is missing required fields: {', '.join(missing)}")
    unexpected = sorted(set(record) - required)
    if unexpected:
        raise GazeNormalizationError(f"gaze record has unexpected fields: {', '.join(unexpected)}")
    if record["schema_version"] != "1.0.0":
        raise GazeNormalizationError("unsupported GazeRecord schema_version")
    for field in ("sample_id", "session_id"):
        if not isinstance(record[field], str) or not record[field]:
            raise GazeNormalizationError(f"{field} must be a non-empty string")
    if record["coordinate_space"] != "viewport_normalized":
        raise GazeNormalizationError("coordinate_space must be viewport_normalized")
    try:
        _parse_utc_timestamp(record["occurred_at"])
    except ValueError as exc:
        raise GazeNormalizationError(str(exc)) from exc
    if not isinstance(record["valid"], bool):
        raise GazeNormalizationError("valid must be a boolean")
    if record["calibration_status"] not in CALIBRATION_STATUSES:
        raise GazeNormalizationError("unsupported calibration_status")
    if not isinstance(record["quality_flags"], list) or any(
        not isinstance(flag, str) for flag in record["quality_flags"]
    ):
        raise GazeNormalizationError("quality_flags must be an array of strings")
    for field in ("x_normalized", "y_normalized"):
        value = record[field]
        if value is not None and not 0 <= _number(value, field) <= 1:
            raise GazeNormalizationError(f"{field} must be between 0 and 1")
    confidence = record["confidence"]
    if confidence is not None and not 0 <= _number(confidence, "confidence") <= 1:
        raise GazeNormalizationError("confidence must be between 0 and 1")


def _calibration_status(records: list[dict[str, Any]]) -> str:
    statuses = {record["calibration_status"] for record in records}
    if not statuses:
        return "pending"
    if "failed" in statuses:
        return "failed"
    if "pending" in statuses:
        return "pending"
    if len(statuses) == 1:
        return statuses.pop()
    return "low_quality"


def evaluate_gaze_quality(records: list[dict[str, Any]]) -> GazeQualityAssessment:
    """Evaluate canonical records without estimating calibrated accuracy.

    A session is ``usable`` when it has at least three valid samples, at least
    half of all samples are valid, and available valid-sample confidence has a
    mean of at least 0.5. Missing provider confidence is reported as
    ``usable_unverified``: valid coordinates remain usable, but no numeric
    confidence claim is made. Explicit low confidence and invalid samples
    still fail the quality gate.
    """

    seen: set[str] = set()
    for record in records:
        _validate_record(record)
        if record["sample_id"] in seen:
            raise DuplicateSampleIdentity(f"duplicate sample_id: {record['sample_id']!r}")
        seen.add(record["sample_id"])

    sample_count = len(records)
    valid_records = [
        record
        for record in records
        if record["valid"] and record["x_normalized"] is not None and record["y_normalized"] is not None
    ]
    valid_sample_count = len(valid_records)
    valid_fraction = valid_sample_count / sample_count if sample_count else 0.0
    confidences = [record["confidence"] for record in valid_records if record["confidence"] is not None]
    mean_confidence = fmean(confidences) if confidences else None
    missing_valid_confidence = any(record["confidence"] is None for record in valid_records)

    flags = {flag for record in records for flag in record["quality_flags"]}
    missingness: set[str] = set()
    if not records:
        quality_status = "no_samples"
        missingness.add("gaze.no_samples")
        flags.add("quality.no_valid_samples")
    elif not valid_records:
        quality_status = "insufficient_data"
        missingness.add("gaze.no_samples")
        flags.add("quality.no_valid_samples")
    elif valid_sample_count < MIN_VALID_SAMPLES:
        quality_status = "insufficient_data"
        missingness.add("gaze.no_samples")
        flags.add("quality.insufficient_samples")
    elif valid_fraction < MIN_VALID_FRACTION:
        quality_status = "low_quality"
        missingness.add("gaze.low_quality")
        flags.add("quality.low_valid_fraction")
    elif missing_valid_confidence:
        quality_status = USABLE_UNVERIFIED
        missingness.add("gaze.quality_unverified")
        flags.add("quality.confidence_missing")
    elif mean_confidence < MIN_MEAN_CONFIDENCE:
        quality_status = "low_quality"
        missingness.add("gaze.low_quality")
        flags.add("quality.low_confidence")
    else:
        quality_status = "usable"

    return GazeQualityAssessment(
        quality_status=quality_status,
        calibration_status=_calibration_status(records),
        sample_count=sample_count,
        valid_sample_count=valid_sample_count,
        valid_fraction=valid_fraction,
        mean_confidence=mean_confidence,
        quality_flags=tuple(sorted(flags)),
        missingness=tuple(sorted(missingness)),
    )
