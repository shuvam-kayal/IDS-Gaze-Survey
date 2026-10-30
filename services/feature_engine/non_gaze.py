"""P3-owned non-gaze features; missing gaze is never imputed as zero."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from services.telemetry.ingestion import deduplicate_events

FEATURE_SET_VERSION = "1.0.0"
DEFAULT_GAZE_MISSINGNESS = "gaze.unavailable"


def build_non_gaze_features(
    events: list[dict[str, Any]], *, survey_completion_ratio: float | None = None
) -> dict[str, int | float | None]:
    clicks = sum(1 for event in events if event.get("event_type") == "interaction.click")
    scroll = 0.0
    previous_position: tuple[float, float] | None = None
    for event in events:
        if event.get("event_type") != "interaction.scroll":
            continue
        payload = event.get("payload", {})
        if "scroll_delta_px" in payload:
            # Keep compatibility with existing event producers that report a
            # signed vertical delta directly.
            scroll += float(payload.get("scroll_delta_px") or 0)
            previous_position = None
            continue
        if "scroll_x_px" in payload or "scroll_y_px" in payload:
            # The participant SDK reports absolute scroll offsets. Derive the
            # distance travelled from consecutive observations.
            position = (float(payload.get("scroll_x_px") or 0), float(payload.get("scroll_y_px") or 0))
            if previous_position is not None:
                scroll += abs(position[0] - previous_position[0]) + abs(position[1] - previous_position[1])
            previous_position = position
    return {
        "interaction.click_count": clicks,
        "interaction.scroll_distance_px": scroll,
        "survey.completion_ratio": survey_completion_ratio,
    }


def _context_from_events(events: list[dict[str, Any]]) -> tuple[str, str, str]:
    contexts = {
        (event["experience_id"], event["session_id"], tuple(event["study_ids"]))
        for event in events
    }
    if len(contexts) != 1:
        raise ValueError("events must share one experience, session, and study context")

    experience_id, session_id, study_ids = next(iter(contexts))
    if len(study_ids) != 1:
        raise ValueError("FeatureRecord generation requires exactly one study_id")
    return experience_id, session_id, study_ids[0]


def _validate_explicit_context(
    events: list[dict[str, Any]], *, experience_id: str, session_id: str, study_id: str
) -> None:
    """Validate one per-Study record against multi-Study event envelopes."""
    for event in events:
        if event["experience_id"] != experience_id:
            raise ValueError("event experience_id does not match explicit FeatureRecord context")
        if event["session_id"] != session_id:
            raise ValueError("event session_id does not match explicit FeatureRecord context")
        if study_id not in event["study_ids"]:
            raise ValueError("event study_ids do not include explicit FeatureRecord study_id")


def build_non_gaze_feature_record(
    events: list[dict[str, Any]],
    *,
    experience_id: str | None = None,
    study_id: str | None = None,
    session_id: str | None = None,
    feature_set_version: str = FEATURE_SET_VERSION,
    config_version: str | None = None,
    aoi_set_version: str | None = None,
    survey_completion_ratio: float | None = None,
    gaze_missingness_reason: str = DEFAULT_GAZE_MISSINGNESS,
    feature_record_id: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic schema-shaped non-gaze FeatureRecord.

    Empty batches require explicit context because there is no event from which
    to infer the experience, study, or session. The current frozen schema does
    not require a provenance object, so provenance is represented by its
    existing version and source-event fields only.
    """

    if not isinstance(feature_set_version, str) or not feature_set_version:
        raise ValueError("feature_set_version must be a non-empty string")
    if not isinstance(gaze_missingness_reason, str) or not gaze_missingness_reason:
        raise ValueError("gaze_missingness_reason must be a non-empty string")

    unique_events = deduplicate_events(events)
    if unique_events:
        supplied = (experience_id, session_id, study_id)
        if all(value is not None for value in supplied):
            _validate_explicit_context(
                unique_events,
                experience_id=experience_id,
                session_id=session_id,
                study_id=study_id,
            )
        else:
            inferred_experience, inferred_session, inferred_study = _context_from_events(
                unique_events
            )
            inferred = (inferred_experience, inferred_session, inferred_study)
            for name, actual, expected in zip(
                ("experience_id", "session_id", "study_id"), supplied, inferred
            ):
                if actual is not None and actual != expected:
                    raise ValueError(f"{name} does not match event context")
            experience_id, session_id, study_id = inferred
    elif not all(
        isinstance(value, str) and value for value in (experience_id, study_id, session_id)
    ):
        raise ValueError("empty input requires experience_id, study_id, and session_id")

    feature_values = build_non_gaze_features(
        unique_events, survey_completion_ratio=survey_completion_ratio
    )
    if feature_record_id is None:
        identity = json.dumps(
            {
                "feature_set_version": feature_set_version,
                "experience_id": experience_id,
                "study_id": study_id,
                "session_id": session_id,
                "event_ids": [event["event_id"] for event in unique_events],
                "features": feature_values,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        feature_record_id = f"feat-{sha256(identity).hexdigest()[:16]}"

    return {
        "schema_version": "1.0.0",
        "feature_record_id": feature_record_id,
        "experience_id": experience_id,
        "study_id": study_id,
        "session_id": session_id,
        "feature_set_version": feature_set_version,
        "config_version": config_version,
        "aoi_set_version": aoi_set_version,
        "modality": "non_gaze_only",
        "window": None,
        "features": feature_values,
        "quality": {
            "gaze_available": False,
            "missingness": [gaze_missingness_reason],
            "calibration_status": None,
        },
        "source_event_count": len(unique_events),
    }
