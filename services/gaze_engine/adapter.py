"""Provider boundary and deterministic ProviderSample -> GazeRecord normalization."""

from __future__ import annotations

from datetime import UTC
from math import isfinite
from typing import Any, Protocol

from services.telemetry.ingestion import _parse_utc_timestamp

GAZE_SCHEMA_VERSION = "1.0.0"
DEFAULT_CALIBRATION_STATUS = "not_required"
CALIBRATION_STATUSES = {"pending", "passed", "failed", "not_required", "low_quality"}


class GazeNormalizationError(ValueError):
    """A ProviderSample cannot be represented as a canonical GazeRecord."""


class DuplicateSampleIdentity(GazeNormalizationError):
    """A session batch contains the same provider sample identity twice."""


class GazeProviderAdapter(Protocol):
    def normalize(
        self,
        provider_sample: dict[str, Any],
        *,
        session_id: str,
        viewport_width_px: float,
        viewport_height_px: float,
        calibration_status: str = DEFAULT_CALIBRATION_STATUS,
    ) -> dict[str, Any]: ...


def _required_string(sample: dict[str, Any], field: str) -> str:
    value = sample.get(field)
    if not isinstance(value, str) or not value:
        raise GazeNormalizationError(f"{field} must be a non-empty string")
    return value


def _finite_number(value: Any, field: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise GazeNormalizationError(f"{field} must be a finite number")
    numeric = float(value)
    if minimum is not None and numeric < minimum:
        raise GazeNormalizationError(f"{field} must be at least {minimum:g}")
    return numeric


def _validate_viewport(width: float, height: float) -> tuple[float, float]:
    numeric_width, numeric_height = (
        _finite_number(width, "viewport_width_px", minimum=0.0),
        _finite_number(height, "viewport_height_px", minimum=0.0),
    )
    if numeric_width == 0 or numeric_height == 0:
        raise GazeNormalizationError("viewport dimensions must be greater than zero")
    return numeric_width, numeric_height


def _normalize_timestamp(value: Any) -> str:
    try:
        parsed = _parse_utc_timestamp(value)
    except ValueError as exc:
        raise GazeNormalizationError(str(exc)) from exc
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _quality_flags(sample: dict[str, Any]) -> list[str]:
    quality = sample.get("quality")
    if not isinstance(quality, dict):
        raise GazeNormalizationError("quality must be an object")
    flags = quality.get("flags")
    if not isinstance(flags, list) or any(not isinstance(flag, str) or not flag for flag in flags):
        raise GazeNormalizationError("quality.flags must be an array of non-empty strings")
    return sorted(set(flags))


def normalize_provider_sample(
    provider_sample: dict[str, Any],
    *,
    session_id: str,
    viewport_width_px: float,
    viewport_height_px: float,
    calibration_status: str = DEFAULT_CALIBRATION_STATUS,
) -> dict[str, Any]:
    """Normalize one ProviderSample into a schema-shaped GazeRecord.

    Provider-invalid samples and samples with missing coordinates remain
    invalid. Malformed values and coordinates outside the supplied viewport
    are rejected instead of being coerced into gaze.
    """

    if not isinstance(provider_sample, dict):
        raise GazeNormalizationError("provider_sample must be an object")
    required_fields = {
        "schema_version",
        "provider",
        "provider_version",
        "sample_id",
        "capture_time_ms",
        "occurred_at",
        "x_px",
        "y_px",
        "valid",
        "quality",
    }
    missing_fields = sorted(required_fields - provider_sample.keys())
    if missing_fields:
        raise GazeNormalizationError(
            f"provider_sample is missing required fields: {', '.join(missing_fields)}"
        )
    unexpected_fields = sorted(set(provider_sample) - required_fields)
    if unexpected_fields:
        raise GazeNormalizationError(
            f"provider_sample has unexpected fields: {', '.join(unexpected_fields)}"
        )
    if not isinstance(session_id, str) or not session_id:
        raise GazeNormalizationError("session_id must be a non-empty string")
    if calibration_status not in CALIBRATION_STATUSES:
        raise GazeNormalizationError("unsupported calibration_status")
    width, height = _validate_viewport(viewport_width_px, viewport_height_px)

    if provider_sample.get("schema_version") != GAZE_SCHEMA_VERSION:
        raise GazeNormalizationError(
            f"unsupported provider sample schema_version: {provider_sample.get('schema_version')!r}"
        )
    _required_string(provider_sample, "provider")
    _required_string(provider_sample, "provider_version")
    sample_id = _required_string(provider_sample, "sample_id")
    _finite_number(provider_sample.get("capture_time_ms"), "capture_time_ms", minimum=0.0)
    occurred_at = _normalize_timestamp(provider_sample.get("occurred_at"))

    valid = provider_sample.get("valid")
    if not isinstance(valid, bool):
        raise GazeNormalizationError("valid must be a boolean")
    flags = _quality_flags(provider_sample)
    quality = provider_sample["quality"]
    if "confidence" not in quality:
        raise GazeNormalizationError("quality is missing required field: confidence")
    confidence = quality.get("confidence")
    if confidence is not None:
        confidence = _finite_number(confidence, "quality.confidence")
        if confidence > 1:
            raise GazeNormalizationError("quality.confidence must be at most 1")
    else:
        flags.append("gaze.confidence_missing")

    x_px, y_px = provider_sample.get("x_px"), provider_sample.get("y_px")
    if (x_px is None) != (y_px is None):
        raise GazeNormalizationError("x_px and y_px must both be null or both be numbers")
    if x_px is None:
        x_normalized = y_normalized = None
        flags.append("gaze.coordinates_missing")
        coordinates_valid = False
    else:
        x_px = _finite_number(x_px, "x_px")
        y_px = _finite_number(y_px, "y_px")
        if not 0 <= x_px <= width or not 0 <= y_px <= height:
            raise GazeNormalizationError("coordinates must be inside the viewport bounds")
        x_normalized = x_px / width
        y_normalized = y_px / height
        coordinates_valid = True

    if not valid:
        flags.append("provider.invalid")

    return {
        "schema_version": GAZE_SCHEMA_VERSION,
        "sample_id": sample_id,
        "session_id": session_id,
        "occurred_at": occurred_at,
        "coordinate_space": "viewport_normalized",
        "x_normalized": x_normalized,
        "y_normalized": y_normalized,
        "confidence": confidence,
        "valid": bool(valid and coordinates_valid),
        "calibration_status": calibration_status,
        "quality_flags": sorted(set(flags)),
    }


def normalize_provider_samples(
    provider_samples: list[dict[str, Any]],
    *,
    session_id: str,
    viewport_width_px: float,
    viewport_height_px: float,
    calibration_status: str = DEFAULT_CALIBRATION_STATUS,
) -> list[dict[str, Any]]:
    """Normalize and deterministically order a session-scoped sample batch."""

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sample in provider_samples:
        sample_id = sample.get("sample_id") if isinstance(sample, dict) else None
        if sample_id in seen:
            raise DuplicateSampleIdentity(f"duplicate sample_id: {sample_id!r}")
        record = normalize_provider_sample(
            sample,
            session_id=session_id,
            viewport_width_px=viewport_width_px,
            viewport_height_px=viewport_height_px,
            calibration_status=calibration_status,
        )
        seen.add(record["sample_id"])
        normalized.append(record)
    return sorted(normalized, key=lambda record: (record["occurred_at"], record["sample_id"]))


class ProviderSampleAdapter:
    """Provider-neutral adapter for the frozen ProviderSample boundary."""

    def normalize(self, provider_sample: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return normalize_provider_sample(provider_sample, **kwargs)

    def normalize_batch(
        self, provider_samples: list[dict[str, Any]], **kwargs: Any
    ) -> list[dict[str, Any]]:
        return normalize_provider_samples(provider_samples, **kwargs)


class NotConfiguredGazeAdapter:
    def normalize(self, provider_sample: dict[str, Any], *, session_id: str) -> dict[str, Any]:
        raise NotImplementedError(
            "Configure an approved provider and implement canonical GazeRecord normalization."
        )
