"""Server-side validation boundary for participant geometry submissions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from services.gaze_engine.adapter import GazeNormalizationError
from services.gaze_engine.context import utc_timestamp
from services.gaze_engine.geometry import GeometryScope, validate_geometry_snapshot
from services.gaze_engine.lifecycle import resolve_authorized_trial_lifecycle

SERVER_VALIDATED_PROVENANCE = "server_validated"


def _assigned_study(assignment: dict[str, Any], *, session_id: str, experience_id: str, study_id: str) -> dict[str, Any]:
    if not isinstance(assignment, dict) or assignment.get("session_id") != session_id or assignment.get("experience_id") != experience_id:
        raise GazeNormalizationError("participant assignment does not match verified session")
    entries = assignment.get("assignments")
    if not isinstance(entries, list):
        raise GazeNormalizationError("participant assignment is invalid")
    matches = [item for item in entries if isinstance(item, dict) and item.get("study_id") == study_id]
    if len(matches) != 1:
        raise GazeNormalizationError("study is not unambiguously assigned to participant session")
    return matches[0]


def _configured_aoi_ids(study_config: dict[str, Any], *, aoi_set_version: str) -> dict[str, dict[str, Any]]:
    aoi_config = study_config.get("aoi_config")
    if not isinstance(aoi_config, dict) or aoi_config.get("config_version") != aoi_set_version:
        raise GazeNormalizationError("assigned AOI configuration is missing or not pinned")
    items = aoi_config.get("items")
    if not isinstance(items, list):
        raise GazeNormalizationError("assigned AOI configuration is invalid")
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("aoi_id"), str) or not item["aoi_id"]:
            raise GazeNormalizationError("assigned AOI configuration contains an invalid AOI")
        if item["aoi_id"] in result:
            raise GazeNormalizationError("assigned AOI configuration contains duplicate AOIs")
        result[item["aoi_id"]] = item
    return result


def validate_server_geometry_submission(
    snapshot: dict[str, Any],
    *,
    participant_session: dict[str, Any],
    assignment: dict[str, Any],
    study_id: str,
    trial_id: str,
    event_repository: Any,
    now: datetime | None = None,
) -> tuple[dict[str, Any], GeometryScope]:
    """Validate a browser snapshot against only server-owned state.

    ``study_id`` and ``trial_id`` select state; neither is trusted until the
    assignment and persisted lifecycle events validate them. The returned
    scope is safe to pass to the v2 validator and persistence layer.
    """
    if not isinstance(participant_session, dict):
        raise GazeNormalizationError("verified participant session is required")
    session_id = participant_session.get("session_id")
    experience_id = participant_session.get("experience_id")
    if not isinstance(session_id, str) or not session_id or not isinstance(experience_id, str) or not experience_id:
        raise GazeNormalizationError("verified participant session is invalid")
    if participant_session.get("status") != "open" or participant_session.get("withdrawn_at") is not None:
        raise GazeNormalizationError("participant session is not open")
    expires_at = participant_session.get("expires_at")
    expiry = expires_at if isinstance(expires_at, datetime) else utc_timestamp(expires_at, "participant session expires_at")
    reference = now or datetime.now(UTC)
    if (
        reference.tzinfo is None
        or reference.utcoffset() != UTC.utcoffset(None)
        or expiry.tzinfo is None
        or expiry.utcoffset() != UTC.utcoffset(None)
        or expiry <= reference.astimezone(UTC)
    ):
        raise GazeNormalizationError("participant session is expired or has an invalid clock")

    selected = _assigned_study(assignment, session_id=session_id, experience_id=experience_id, study_id=study_id)
    config = selected.get("study_config")
    if not isinstance(config, dict):
        raise GazeNormalizationError("assigned study configuration is invalid")
    aoi_set_version = config.get("aoi_set_version")
    if not isinstance(aoi_set_version, str) or not aoi_set_version:
        raise GazeNormalizationError("assigned study has no pinned AOI-set version")
    configured = _configured_aoi_ids(config, aoi_set_version=aoi_set_version)
    scope = GeometryScope(session_id, study_id, aoi_set_version)
    normalized = validate_geometry_snapshot(snapshot, scope=scope)
    for rectangle in normalized["rectangles"]:
        aoi = configured.get(rectangle["aoi_id"])
        if aoi is None:
            raise GazeNormalizationError("geometry rectangle references an unconfigured AOI")
        if isinstance(aoi.get("priority"), int) and rectangle["priority"] != aoi["priority"]:
            raise GazeNormalizationError("geometry rectangle priority does not match pinned AOI configuration")

    lifecycle, reason = resolve_authorized_trial_lifecycle(
        event_repository,
        participant_session=participant_session,
        study_assignment=assignment,
        study_id=study_id,
        trial_id=trial_id,
        aoi_set_version=aoi_set_version,
        now=reference,
    )
    if lifecycle is None:
        raise GazeNormalizationError(reason or "trial observation window is unavailable")
    captured_at = utc_timestamp(normalized["captured_at"], "geometry captured_at")
    start = utc_timestamp(lifecycle.window_start, "trial observation start")
    end = utc_timestamp(lifecycle.window_end, "trial observation end")
    if not start <= captured_at < end:
        raise GazeNormalizationError("geometry captured_at is outside the trial observation window")
    return normalized, scope
