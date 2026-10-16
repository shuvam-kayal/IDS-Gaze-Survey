"""Study-scoped trial exposure lifecycle resolution."""

from __future__ import annotations

import json
from typing import Any

from services.gaze_engine.adapter import GazeNormalizationError
from services.gaze_engine.context import TrialObservationContext, utc_timestamp

START_EVENT_TYPE = "trial.exposure_started"
END_EVENT_TYPE = "trial.exposure_ended"
START_MISSING = "gaze.observation_start_missing"
END_MISSING = "gaze.observation_end_missing"
BOUNDARY_AMBIGUOUS = "gaze.observation_boundary_ambiguous"


def _validate_event(event: dict[str, Any], *, session_id: str, study_id: str, trial_id: str | None, event_type: str) -> str:
    required = {"schema_version", "event_id", "experience_id", "study_ids", "session_id", "event_type", "occurred_at", "payload"}
    if not isinstance(event, dict) or not required.issubset(event):
        raise GazeNormalizationError("trial lifecycle event is missing required fields")
    if event["schema_version"] != "1.0.0" or event["event_type"] != event_type:
        raise GazeNormalizationError("unsupported trial lifecycle event")
    if event["session_id"] != session_id or event["study_ids"] != [study_id]:
        raise GazeNormalizationError("trial lifecycle event study/session context does not match")
    if not isinstance(event["payload"], dict) or not isinstance(event["payload"].get("trial_id"), str):
        raise GazeNormalizationError("trial lifecycle payload requires trial_id")
    found_trial = event["payload"]["trial_id"]
    if trial_id is not None and found_trial != trial_id:
        raise GazeNormalizationError("trial lifecycle event trial_id does not match context")
    utc_timestamp(event["occurred_at"], "trial lifecycle occurred_at")
    return found_trial


def _unique(events: list[dict[str, Any]], *, session_id: str, study_id: str, trial_id: str | None, event_type: str) -> list[dict[str, Any]]:
    by_id: dict[str, tuple[str, dict[str, Any]]] = {}
    for event in events:
        _validate_event(event, session_id=session_id, study_id=study_id, trial_id=trial_id, event_type=event_type)
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
) -> tuple[TrialObservationContext | None, str | None]:
    """Resolve exact retries and require one unambiguous start/end pair."""

    starts = _unique(start_events, session_id=session_id, study_id=study_id, trial_id=trial_id, event_type=START_EVENT_TYPE)
    ends = _unique(end_events, session_id=session_id, study_id=study_id, trial_id=trial_id, event_type=END_EVENT_TYPE)
    if not starts:
        return None, START_MISSING
    if not ends:
        return None, END_MISSING
    if len(starts) != 1 or len(ends) != 1:
        return None, BOUNDARY_AMBIGUOUS
    resolved_trial = _validate_event(starts[0], session_id=session_id, study_id=study_id, trial_id=trial_id, event_type=START_EVENT_TYPE)
    _validate_event(ends[0], session_id=session_id, study_id=study_id, trial_id=resolved_trial, event_type=END_EVENT_TYPE)
    start = utc_timestamp(starts[0]["occurred_at"], "start_event.occurred_at")
    end = utc_timestamp(ends[0]["occurred_at"], "end_event.occurred_at")
    if end <= start:
        return None, "gaze.observation_boundary_invalid"
    return TrialObservationContext(session_id, study_id, resolved_trial, aoi_set_version, starts[0]["occurred_at"], ends[0]["occurred_at"]), None
