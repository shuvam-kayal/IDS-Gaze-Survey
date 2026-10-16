"""Deterministic fixation detection and timestamped AOI mapping.

This module consumes canonical GazeRecords and GeometrySnapshots only. It does
not estimate calibration accuracy or infer geometry that is not present in a
snapshot.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from math import isfinite
from statistics import fmean
from typing import Any

from services.gaze_engine.adapter import DuplicateSampleIdentity, GazeNormalizationError
from services.gaze_engine.context import TrialObservationContext, validate_observation_association
from services.gaze_engine.quality import evaluate_gaze_quality
from services.telemetry.ingestion import _parse_utc_timestamp

FIXATION_ALGORITHM_VERSION = "gaze-baseline-1"
MAX_GAP_MS = 200
MIN_FIXATION_SAMPLES = 3
MIN_FIXATION_DURATION_MS = 100
MAX_DISPERSION = 0.05
UNUSABLE_FLAGS = {
    "provider.invalid",
    "gaze.permission_denied",
    "gaze.camera_unavailable",
    "gaze.capture_interrupted",
    "gaze.consent_withdrawn",
    "gaze.provider_failure",
    "gaze.not_collected_by_policy",
}


@dataclass(frozen=True)
class Fixation:
    """Internal fixation result; no versioned shared contract is changed."""

    fixation_id: str
    sample_ids: tuple[str, ...]
    start_at: str
    end_at: str
    duration_ms: int
    x_normalized: float
    y_normalized: float
    algorithm_version: str = FIXATION_ALGORITHM_VERSION
    session_id: str | None = None
    study_id: str | None = None
    trial_id: str | None = None
    aoi_set_version: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AOIAssignment:
    """Internal mapping result for a sample or fixation observation."""

    observation_id: str
    aoi_id: str
    snapshot_id: str | None
    reason: str | None
    session_id: str | None = None
    study_id: str | None = None
    trial_id: str | None = None
    aoi_set_version: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _timestamp(value: Any, field: str) -> datetime:
    try:
        return _parse_utc_timestamp(value)
    except (TypeError, ValueError) as exc:
        raise GazeNormalizationError(f"{field} must be a valid UTC timestamp") from exc


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise GazeNormalizationError(f"{field} must be a finite number")
    return float(value)


def _validated_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # This reuses the established canonical validation and duplicate identity
    # behavior without changing the quality thresholds or sample meaning.
    evaluate_gaze_quality(records)
    seen: set[str] = set()
    for record in records:
        if record["sample_id"] in seen:
            raise DuplicateSampleIdentity(f"duplicate sample_id: {record['sample_id']!r}")
        seen.add(record["sample_id"])
    return sorted(records, key=lambda record: (_timestamp(record["occurred_at"], "occurred_at"), record["sample_id"]))


def _eligible(record: dict[str, Any]) -> bool:
    if not record["valid"] or record["x_normalized"] is None or record["y_normalized"] is None:
        return False
    return not UNUSABLE_FLAGS.intersection(record["quality_flags"])


def _dispersion(records: list[dict[str, Any]]) -> tuple[float, float]:
    xs = [record["x_normalized"] for record in records]
    ys = [record["y_normalized"] for record in records]
    return max(xs) - min(xs), max(ys) - min(ys)


def detect_fixations(
    records: list[dict[str, Any]], *, context: TrialObservationContext | None = None
) -> list[Fixation]:
    """Detect greedy, non-overlapping dispersion-duration fixations.

    Records are ordered by UTC occurrence timestamp and sample ID. Invalid or
    unusable samples and gaps greater than 200 ms split traces. Within each
    contiguous run, the detector grows a window while both coordinate
    dispersions stay at most 0.05. A fixation is emitted only for a window with
    at least three samples spanning at least 100 ms; the longest qualifying
    window from the current start is emitted, then detection resumes after it.
    """

    ordered = _validated_records(records)
    if context is not None:
        for record in ordered:
            occurred = _timestamp(record["occurred_at"], "occurred_at")
            if record["session_id"] != context.session_id or not (context.start <= occurred < context.end):
                raise GazeNormalizationError("gaze record is outside the trial observation context")
    fixations: list[Fixation] = []
    run: list[dict[str, Any]] = []

    def flush_run(samples: list[dict[str, Any]]) -> None:
        index = 0
        while index < len(samples):
            end = index
            last_qualifying: int | None = None
            while end < len(samples):
                candidate = samples[index : end + 1]
                x_dispersion, y_dispersion = _dispersion(candidate)
                if x_dispersion > MAX_DISPERSION or y_dispersion > MAX_DISPERSION:
                    break
                start_time = _timestamp(candidate[0]["occurred_at"], "occurred_at")
                end_time = _timestamp(candidate[-1]["occurred_at"], "occurred_at")
                duration_ms = int((end_time - start_time).total_seconds() * 1000)
                if len(candidate) >= MIN_FIXATION_SAMPLES and duration_ms >= MIN_FIXATION_DURATION_MS:
                    last_qualifying = end
                end += 1
            if last_qualifying is None:
                index += 1
                continue
            candidate = samples[index : last_qualifying + 1]
            start_time = _timestamp(candidate[0]["occurred_at"], "occurred_at")
            end_time = _timestamp(candidate[-1]["occurred_at"], "occurred_at")
            fixations.append(
                Fixation(
                    fixation_id=f"fixation-{len(fixations):04d}",
                    sample_ids=tuple(record["sample_id"] for record in candidate),
                    start_at=candidate[0]["occurred_at"],
                    end_at=candidate[-1]["occurred_at"],
                    duration_ms=int((end_time - start_time).total_seconds() * 1000),
                    x_normalized=fmean(record["x_normalized"] for record in candidate),
                    y_normalized=fmean(record["y_normalized"] for record in candidate),
                    session_id=context.session_id if context else None,
                    study_id=context.study_id if context else None,
                    trial_id=context.trial_id if context else None,
                    aoi_set_version=context.aoi_set_version if context else None,
                )
            )
            index = last_qualifying + 1

    previous_time: datetime | None = None
    for record in ordered:
        current_time = _timestamp(record["occurred_at"], "occurred_at")
        breaks_trace = (
            previous_time is not None
            and (current_time - previous_time).total_seconds() * 1000 > MAX_GAP_MS
        )
        if breaks_trace or not _eligible(record):
            flush_run(run)
            run = []
        if _eligible(record):
            run.append(record)
        previous_time = current_time
    flush_run(run)
    return fixations


def detect_fixations_from_association(association: dict[str, Any]) -> list[Fixation]:
    """Validate explicit trial context before running the detector."""

    context, records = validate_observation_association(association)
    return detect_fixations(records, context=context)


def _valid_rectangle(rectangle: dict[str, Any]) -> bool:
    required = {"aoi_id", "left_px", "top_px", "right_px", "bottom_px", "priority"}
    if not isinstance(rectangle, dict) or not required.issubset(rectangle):
        return False
    if set(rectangle) != required:
        return False
    if not isinstance(rectangle["aoi_id"], str) or not rectangle["aoi_id"]:
        return False
    if isinstance(rectangle["priority"], bool) or not isinstance(rectangle["priority"], int):
        return False
    try:
        left = _finite(rectangle["left_px"], "left_px")
        top = _finite(rectangle["top_px"], "top_px")
        right = _finite(rectangle["right_px"], "right_px")
        bottom = _finite(rectangle["bottom_px"], "bottom_px")
    except GazeNormalizationError:
        return False
    return right > left and bottom > top


def _snapshots(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    required = {
        "schema_version",
        "snapshot_id",
        "session_id",
        "captured_at",
        "aoi_set_version",
        "viewport_width_px",
        "viewport_height_px",
        "scroll_x_px",
        "scroll_y_px",
        "zoom",
        "rectangles",
    }
    for snapshot in snapshots:
        if not isinstance(snapshot, dict) or not required.issubset(snapshot):
            continue
        if snapshot["schema_version"] not in {"1.0.0", "2.0.0"}:
            continue
        snapshot_id = snapshot["snapshot_id"]
        session_id = snapshot["session_id"]
        if not isinstance(snapshot_id, str) or not snapshot_id or not isinstance(session_id, str) or not session_id:
            continue
        study_id = snapshot.get("study_id")
        if snapshot["schema_version"] == "2.0.0" and (not isinstance(study_id, str) or not study_id):
            continue
        if snapshot_id in seen:
            raise DuplicateSampleIdentity(f"duplicate snapshot_id: {snapshot_id!r}")
        try:
            captured_at = _timestamp(snapshot["captured_at"], "captured_at")
            width = _finite(snapshot["viewport_width_px"], "viewport_width_px")
            height = _finite(snapshot["viewport_height_px"], "viewport_height_px")
            _finite(snapshot["scroll_x_px"], "scroll_x_px")
            _finite(snapshot["scroll_y_px"], "scroll_y_px")
            zoom = _finite(snapshot["zoom"], "zoom")
        except GazeNormalizationError:
            continue
        if width <= 0 or height <= 0 or zoom <= 0 or not isinstance(snapshot["rectangles"], list):
            continue
        normalized.append(
            {
                **snapshot,
                "_captured_at": captured_at,
                "_width": width,
                "_height": height,
                "_study_id": study_id,
            }
        )
        seen.add(snapshot_id)
    return sorted(normalized, key=lambda snapshot: (snapshot["_captured_at"], snapshot["snapshot_id"]))


def _snapshot_for(
    snapshots: list[dict[str, Any]],
    session_id: str,
    at: datetime,
    *,
    study_id: str | None = None,
    aoi_set_version: str | None = None,
) -> dict[str, Any] | None:
    eligible = [
        snapshot
        for snapshot in snapshots
        if snapshot["session_id"] == session_id
        and snapshot["_captured_at"] <= at
        and (study_id is None or snapshot["_study_id"] == study_id)
        and (aoi_set_version is None or snapshot["aoi_set_version"] == aoi_set_version)
    ]
    return eligible[-1] if eligible else None


def _resolve_aoi(snapshot: dict[str, Any], x_normalized: float, y_normalized: float) -> str | None:
    x_px = x_normalized * snapshot["_width"]
    y_px = y_normalized * snapshot["_height"]
    matches = []
    for rectangle in snapshot["rectangles"]:
        if not _valid_rectangle(rectangle):
            continue
        if rectangle["left_px"] <= x_px < rectangle["right_px"] and rectangle["top_px"] <= y_px < rectangle["bottom_px"]:
            matches.append(rectangle)
    if not matches:
        return None
    return min(matches, key=lambda rectangle: (-rectangle["priority"], rectangle["aoi_id"]))["aoi_id"]


def map_gaze_to_aois(
    records: list[dict[str, Any]],
    geometry_snapshots: list[dict[str, Any]],
    *,
    study_id: str | None = None,
    aoi_set_version: str | None = None,
) -> list[AOIAssignment]:
    """Map samples using the latest prior study/version-matched snapshot."""

    ordered = _validated_records(records)
    snapshots = _snapshots(geometry_snapshots)
    versions = {(snapshot["_study_id"], snapshot["aoi_set_version"]) for snapshot in snapshots}
    if (study_id is None or aoi_set_version is None) and (len(versions) > 1 or any(snapshot["schema_version"] == "2.0.0" for snapshot in snapshots)):
        raise GazeNormalizationError("study_id and aoi_set_version are required for multi-study AOI mapping")
    assignments: list[AOIAssignment] = []
    for record in ordered:
        if not _eligible(record):
            reason = "gaze.invalid" if not record["valid"] else "gaze.coordinates_missing"
            assignments.append(AOIAssignment(record["sample_id"], "aoi.unresolved", None, reason, record["session_id"], study_id, None, aoi_set_version))
            continue
        at = _timestamp(record["occurred_at"], "occurred_at")
        snapshot = _snapshot_for(
            snapshots,
            record["session_id"],
            at,
            study_id=study_id,
            aoi_set_version=aoi_set_version,
        )
        if snapshot is None:
            assignments.append(AOIAssignment(record["sample_id"], "aoi.unresolved", None, "aoi.unresolved", record["session_id"], study_id, None, aoi_set_version))
            continue
        aoi_id = _resolve_aoi(snapshot, record["x_normalized"], record["y_normalized"])
        assignments.append(
            AOIAssignment(
                record["sample_id"],
                aoi_id or "aoi.unresolved",
                snapshot["snapshot_id"],
                None if aoi_id else "aoi.unresolved",
                record["session_id"], study_id, None, aoi_set_version,
            )
        )
    return assignments


def map_fixations_to_aois(
    fixations: list[Fixation],
    session_id: str,
    geometry_snapshots: list[dict[str, Any]],
    *,
    study_id: str | None = None,
    aoi_set_version: str | None = None,
) -> list[AOIAssignment]:
    """Map fixation centroids using a study/version-matched snapshot."""

    snapshots = _snapshots(geometry_snapshots)
    versions = {(snapshot["_study_id"], snapshot["aoi_set_version"]) for snapshot in snapshots}
    if (study_id is None or aoi_set_version is None) and (len(versions) > 1 or any(snapshot["schema_version"] == "2.0.0" for snapshot in snapshots)):
        raise GazeNormalizationError("study_id and aoi_set_version are required for multi-study AOI mapping")
    assignments: list[AOIAssignment] = []
    for fixation in fixations:
        snapshot = _snapshot_for(
            snapshots,
            session_id,
            _timestamp(fixation.start_at, "start_at"),
            study_id=study_id,
            aoi_set_version=aoi_set_version,
        )
        if snapshot is None:
            assignments.append(AOIAssignment(fixation.fixation_id, "aoi.unresolved", None, "aoi.unresolved", session_id, study_id, fixation.trial_id, aoi_set_version))
            continue
        aoi_id = _resolve_aoi(snapshot, fixation.x_normalized, fixation.y_normalized)
        assignments.append(
            AOIAssignment(
                fixation.fixation_id,
                aoi_id or "aoi.unresolved",
                snapshot["snapshot_id"],
                None if aoi_id else "aoi.unresolved",
                session_id, study_id, fixation.trial_id, aoi_set_version,
            )
        )
    return assignments
