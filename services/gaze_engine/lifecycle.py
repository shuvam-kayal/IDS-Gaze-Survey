"""Study-scoped trial exposure lifecycle resolution."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from services.gaze_engine.adapter import GazeNormalizationError
from services.gaze_engine.context import TrialObservationContext, utc_timestamp

START_EVENT_TYPE = "trial.exposure_started"
END_EVENT_TYPE = "trial.exposure_ended"
START_MISSING = "gaze.observation_start_missing"
END_MISSING = "gaze.observation_end_missing"
BOUNDARY_AMBIGUOUS = "gaze.observation_boundary_ambiguous"


def _validate_event(
    event: dict[str, Any],
    *,
    session_id: str,
    study_id: str,
    trial_id: str | None,
    event_type: str,
    experience_id: str | None = None,
) -> str:
    required = {"schema_version", "event_id", "experience_id", "study_ids", "session_id", "event_type", "occurred_at", "payload"}
    if not isinstance(event, dict) or not required.issubset(event):
        raise GazeNormalizationError("trial lifecycle event is missing required fields")
    if event["schema_version"] != "1.0.0" or event["event_type"] != event_type:
        raise GazeNormalizationError("unsupported trial lifecycle event")
    if not isinstance(event.get("event_id"), str) or not event["event_id"]:
        raise GazeNormalizationError("trial lifecycle event event_id is invalid")
    if not isinstance(event.get("experience_id"), str) or not event["experience_id"]:
        raise GazeNormalizationError("trial lifecycle event experience_id is invalid")
    if experience_id is not None and event["experience_id"] != experience_id:
        raise GazeNormalizationError("trial lifecycle event Experience does not match session")
    if event["session_id"] != session_id or event["study_ids"] != [study_id]:
        raise GazeNormalizationError("trial lifecycle event study/session context does not match")
    if not isinstance(event["payload"], dict) or not isinstance(event["payload"].get("trial_id"), str):
        raise GazeNormalizationError("trial lifecycle payload requires trial_id")
    found_trial = event["payload"]["trial_id"]
    if trial_id is not None and found_trial != trial_id:
        raise GazeNormalizationError("trial lifecycle event trial_id does not match context")
    if not isinstance(event.get("occurred_at"), str):
        raise GazeNormalizationError("trial lifecycle occurred_at is invalid")
    utc_timestamp(event["occurred_at"], "trial lifecycle occurred_at")
    return found_trial


def _unique(
    events: list[dict[str, Any]],
    *,
    session_id: str,
    study_id: str,
    trial_id: str | None,
    event_type: str,
    experience_id: str | None = None,
) -> list[dict[str, Any]]:
    by_id: dict[str, tuple[str, dict[str, Any]]] = {}
    for event in events:
        _validate_event(
            event,
            session_id=session_id,
            study_id=study_id,
            trial_id=trial_id,
            event_type=event_type,
            experience_id=experience_id,
        )
        canonical = json.dumps(event, sort_keys=True, separators=(",", ":"))
        event_id = event["event_id"]
        if event_id in by_id and by_id[event_id][0] != canonical:
            raise GazeNormalizationError("conflicting duplicate trial lifecycle event")
        by_id[event_id] = (canonical, event)
    return [entry[1] for entry in sorted(by_id.values(), key=lambda entry: entry[0])]


def resolve_trial_lifecycle(
    start_events: list[dict[str, Any]],
    end_events: list[dict[str, Any]],
    *,
    session_id: str,
    study_id: str,
    aoi_set_version: str,
    trial_id: str | None = None,
    experience_id: str | None = None,
) -> tuple[TrialObservationContext | None, str | None]:
    """Resolve exact retries and require one unambiguous start/end pair."""

    starts = _unique(
        start_events,
        session_id=session_id,
        study_id=study_id,
        trial_id=trial_id,
        event_type=START_EVENT_TYPE,
        experience_id=experience_id,
    )
    ends = _unique(
        end_events,
        session_id=session_id,
        study_id=study_id,
        trial_id=trial_id,
        event_type=END_EVENT_TYPE,
        experience_id=experience_id,
    )
    if not starts:
        return None, START_MISSING
    if not ends:
        return None, END_MISSING
    if len(starts) != 1 or len(ends) != 1:
        return None, BOUNDARY_AMBIGUOUS
    resolved_trial = _validate_event(
        starts[0],
        session_id=session_id,
        study_id=study_id,
        trial_id=trial_id,
        event_type=START_EVENT_TYPE,
        experience_id=experience_id,
    )
    _validate_event(
        ends[0],
        session_id=session_id,
        study_id=study_id,
        trial_id=resolved_trial,
        event_type=END_EVENT_TYPE,
        experience_id=experience_id,
    )
    start = utc_timestamp(starts[0]["occurred_at"], "start_event.occurred_at")
    end = utc_timestamp(ends[0]["occurred_at"], "end_event.occurred_at")
    if end <= start:
        return None, "gaze.observation_boundary_invalid"
    return TrialObservationContext(session_id, study_id, resolved_trial, aoi_set_version, starts[0]["occurred_at"], ends[0]["occurred_at"]), None


def _parse_expiry(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = utc_timestamp(value, "participant session expires_at")
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(None):
        raise GazeNormalizationError("participant session expires_at must be UTC")
    return parsed.astimezone(UTC)


def _pinned_study_assignment(
    assignment: dict[str, Any], *, session_id: str, experience_id: str, study_id: str
) -> dict[str, Any]:
    """Return one study assignment from the server-owned assignment record."""

    if not isinstance(assignment, dict):
        raise GazeNormalizationError("participant study assignment is unavailable")
    if assignment.get("session_id") != session_id or assignment.get("experience_id") != experience_id:
        raise GazeNormalizationError("participant assignment does not match session")
    entries = assignment.get("assignments")
    if not isinstance(entries, list):
        raise GazeNormalizationError("participant assignment is invalid")
    matches = [entry for entry in entries if isinstance(entry, dict) and entry.get("study_id") == study_id]
    if len(matches) != 1:
        raise GazeNormalizationError("study is not unambiguously assigned to participant session")
    selected = matches[0]
    config = selected.get("study_config")
    if not isinstance(config, dict) or not isinstance(config.get("aoi_set_version"), str) or not config["aoi_set_version"]:
        raise GazeNormalizationError("assigned study has no pinned AOI-set version")
    return selected


def resolve_authorized_trial_lifecycle(
    event_repository: Any,
    *,
    participant_session: dict[str, Any],
    study_assignment: dict[str, Any],
    study_id: str,
    trial_id: str,
    aoi_set_version: str,
    now: datetime | None = None,
) -> tuple[TrialObservationContext | None, str | None]:
    """Resolve a window from server-owned session, assignment, and events.

    ``participant_session`` must be the result of the existing credential
    verifier; this function intentionally accepts verified state rather than a
    browser credential.  ``study_assignment`` must come from the server-owned
    assignment repository.  The function does not authenticate either input.
    """

    if not isinstance(trial_id, str) or not trial_id:
        raise GazeNormalizationError("trial_id must be a non-empty string")
    if not isinstance(aoi_set_version, str) or not aoi_set_version:
        raise GazeNormalizationError("aoi_set_version must be a non-empty string")
    if not isinstance(participant_session, dict):
        raise GazeNormalizationError("verified participant session is required")
    session_id = participant_session.get("session_id")
    experience_id = participant_session.get("experience_id")
    if not isinstance(session_id, str) or not session_id or not isinstance(experience_id, str) or not experience_id:
        raise GazeNormalizationError("verified participant session is invalid")
    if participant_session.get("status") != "open":
        raise GazeNormalizationError("participant session is not open")
    reference = now or datetime.now(UTC)
    if reference.tzinfo is None or reference.utcoffset() != UTC.utcoffset(None):
        raise GazeNormalizationError("now must be timezone-aware UTC")
    if _parse_expiry(participant_session.get("expires_at")) <= reference.astimezone(UTC):
        raise GazeNormalizationError("participant session has expired")
    selected = _pinned_study_assignment(
        study_assignment,
        session_id=session_id,
        experience_id=experience_id,
        study_id=study_id,
    )
    pinned_aoi = selected["study_config"]["aoi_set_version"]
    if pinned_aoi != aoi_set_version:
        raise GazeNormalizationError("requested AOI-set version is not pinned for the study")
    if not hasattr(event_repository, "list_events"):
        raise TypeError("event_repository must provide list_events")
    events = event_repository.list_events(session_id, study_id=study_id)
    starts = [event for event in events if event.get("event_type") == START_EVENT_TYPE]
    ends = [event for event in events if event.get("event_type") == END_EVENT_TYPE]
    return resolve_trial_lifecycle(
        starts,
        ends,
        session_id=session_id,
        study_id=study_id,
        aoi_set_version=aoi_set_version,
        trial_id=trial_id,
        experience_id=experience_id,
    )
