"""P3 session-completion orchestration for durable non-gaze FeatureRecords."""

from __future__ import annotations

from typing import Any

from services.feature_engine.non_gaze import FEATURE_SET_VERSION, build_non_gaze_feature_record


def persist_non_gaze_feature_records(
    *,
    session_id: str,
    experience_id: str,
    assignments: list[dict[str, Any]],
    telemetry_repository: Any,
    survey_completion_ratios: dict[str, float | None] | None = None,
    feature_set_version: str = FEATURE_SET_VERSION,
) -> list[dict[str, Any]]:
    """Create one non-gaze record per assigned Study when no P3 record exists.

    This is intentionally invoked only after the participant session has been
    authenticated and the survey submission has been durably accepted. Existing
    gaze FeatureRecords win, so a gaze session is never duplicated by a fallback
    record. Event and Study scope are resolved from server-owned persistence.
    """
    if not isinstance(assignments, list):
        raise TypeError("assignments must be a list")
    ratios = survey_completion_ratios or {}
    created: list[dict[str, Any]] = []
    for assignment in assignments:
        study_id = assignment.get("study_id") if isinstance(assignment, dict) else None
        config = assignment.get("study_config") if isinstance(assignment, dict) else None
        if not isinstance(study_id, str) or not isinstance(config, dict):
            raise ValueError("participant Study assignment is invalid")
        existing = telemetry_repository.list_feature_records(session_id, study_id=study_id)
        if existing:
            continue
        events = telemetry_repository.list_events(session_id, study_id=study_id)
        record = build_non_gaze_feature_record(
            events,
            experience_id=experience_id,
            study_id=study_id,
            session_id=session_id,
            feature_set_version=feature_set_version,
            config_version=config.get("config_version"),
            aoi_set_version=config.get("aoi_set_version"),
            survey_completion_ratio=ratios.get(study_id),
        )
        telemetry_repository.persist_feature_record(record)
        created.append(record)
    return created
