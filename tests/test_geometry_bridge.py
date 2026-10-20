from datetime import UTC, datetime

import pytest
from fastapi import HTTPException, Response

from services.control_plane.router import (
    GeometrySubmissionRequest,
    submit_participant_geometry,
)
from services.gaze_engine.adapter import GazeNormalizationError
from services.gaze_engine.geometry_bridge import validate_server_geometry_submission
from services.telemetry.persistence import RecordIdentityConflict

SESSION = {
    "session_id": "session-a", "experience_id": "experience-a", "status": "open",
    "withdrawn_at": None, "expires_at": "2099-10-20T11:00:00Z",
}
ASSIGNMENT = {
    "session_id": "session-a", "experience_id": "experience-a", "assignments": [{
        "study_id": "study-a", "config_version": "study-v1", "study_config": {
            "aoi_set_version": "aoi-v1",
            "aoi_config": {"config_version": "aoi-v1", "items": [{"aoi_id": "target", "priority": 1}]},
        },
    }],
}


def event(event_id, event_type, occurred_at, *, session_id="session-a", study_id="study-a", trial_id="trial-a"):
    return {
        "schema_version": "1.0.0", "event_id": event_id, "experience_id": "experience-a",
        "study_ids": [study_id], "session_id": session_id, "event_type": event_type,
        "occurred_at": occurred_at, "payload": {"trial_id": trial_id},
    }


def snapshot(captured_at="2026-10-20T10:00:01Z", *, session_id="session-a", study_id="study-a", version="aoi-v1", aoi_id="target"):
    return {
        "schema_version": "2.0.0", "snapshot_id": "geometry-1", "session_id": session_id,
        "study_id": study_id, "captured_at": captured_at, "aoi_set_version": version,
        "viewport_width_px": 1000, "viewport_height_px": 800, "scroll_x_px": 0,
        "scroll_y_px": 0, "zoom": 1, "rectangles": [{
            "aoi_id": aoi_id, "left_px": 10, "top_px": 10, "right_px": 100,
            "bottom_px": 100, "priority": 1,
        }],
    }


class Events:
    def list_events(self, session_id, *, study_id=None):
        return [
            event("start-1", "trial.exposure_started", "2026-10-20T10:00:00Z", session_id=session_id, study_id=study_id),
            event("end-1", "trial.exposure_ended", "2026-10-20T10:01:00Z", session_id=session_id, study_id=study_id),
        ]


def test_server_validation_binds_scope_aoi_and_half_open_trial_window():
    normalized, scope = validate_server_geometry_submission(
        snapshot(), participant_session=SESSION, assignment=ASSIGNMENT,
        study_id="study-a", trial_id="trial-a", event_repository=Events(),
        now=datetime(2026, 10, 20, 10, 30, tzinfo=UTC),
    )
    assert scope.session_id == "session-a"
    assert scope.aoi_set_version == "aoi-v1"
    assert normalized["captured_at"] == "2026-10-20T10:00:01Z"


@pytest.mark.parametrize("bad", [
    {"study_id": "study-b"},
    {"snapshot": snapshot(aoi_id="unknown")},
    {"snapshot": snapshot(version="aoi-old")},
    {"snapshot": snapshot(captured_at="2026-10-20T10:01:00Z")},
    {"snapshot": {**snapshot(), "provenance": "server_validated"}},
])
def test_server_validation_rejects_wrong_scope_unknown_aoi_stale_time_or_client_provenance(bad):
    request_snapshot = bad.get("snapshot", snapshot())
    with pytest.raises((GazeNormalizationError, KeyError)):
        validate_server_geometry_submission(
            request_snapshot, participant_session=SESSION, assignment=ASSIGNMENT,
            study_id=bad.get("study_id", "study-a"), trial_id="trial-a", event_repository=Events(),
            now=datetime(2026, 10, 20, 10, 30, tzinfo=UTC),
        )


def test_server_validation_rejects_expired_withdrawn_and_missing_lifecycle():
    with pytest.raises(GazeNormalizationError, match="expired"):
        validate_server_geometry_submission(
            snapshot(), participant_session={**SESSION, "expires_at": "2026-10-20T10:30:00Z"},
            assignment=ASSIGNMENT, study_id="study-a", trial_id="trial-a", event_repository=Events(),
            now=datetime(2026, 10, 20, 10, 30, tzinfo=UTC),
        )
    with pytest.raises(GazeNormalizationError, match="not open"):
        validate_server_geometry_submission(
            snapshot(), participant_session={**SESSION, "status": "withdrawn", "withdrawn_at": "2026-10-20T10:05:00Z"},
            assignment=ASSIGNMENT, study_id="study-a", trial_id="trial-a", event_repository=Events(),
        )
    with pytest.raises(GazeNormalizationError, match="observation_start_missing"):
        validate_server_geometry_submission(
            snapshot(), participant_session=SESSION, assignment=ASSIGNMENT, study_id="study-a", trial_id="trial-a",
            event_repository=type("NoEvents", (), {"list_events": lambda self, *_args, **_kwargs: []})(),
        )


class ControlRepository:
    def __init__(self):
        self.consents = {"research_participation": "accepted", "camera_gaze": "accepted"}
        self.session = dict(SESSION)

    def verify_participant_session(self, *, session_id, credential):
        return self.session if session_id == "session-a" and credential == "credential-a" else None

    def is_origin_authorized(self, experience_id, origin):
        return experience_id == "experience-a" and origin == "http://localhost:5173"

    def participant_consent_state(self, _session_id):
        return {"consent": [{"scope": scope, "decision": decision} for scope, decision in self.consents.items()]}

    def get_assignment(self, _session_id):
        return ASSIGNMENT


class GeometryRepository(Events):
    def __init__(self):
        self.rows = {}

    def persist_server_validated_geometry_snapshot(self, value, *, trusted_scope):
        key = (trusted_scope.session_id, trusted_scope.study_id, value["snapshot_id"])
        if key in self.rows:
            if self.rows[key] != value:
                raise RecordIdentityConflict("geometry snapshot identity conflict")
            return True
        self.rows[key] = value
        return False


def test_authenticated_route_persists_server_validated_geometry_and_retries():
    control = ControlRepository()
    geometry = GeometryRepository()
    body = GeometrySubmissionRequest(study_id="study-a", trial_id="trial-a", snapshot=snapshot())
    first = submit_participant_geometry("session-a", "study-a", "trial-a", body, Response(), control, geometry, "credential-a", "http://localhost:5173")
    retry = submit_participant_geometry("session-a", "study-a", "trial-a", body, Response(), control, geometry, "credential-a", "http://localhost:5173")
    assert first.provenance == "server_validated"
    assert first.duplicate is False
    assert retry.duplicate is True


def test_authenticated_route_rejects_missing_or_wrong_credential_and_consent():
    control = ControlRepository()
    geometry = GeometryRepository()
    body = GeometrySubmissionRequest(study_id="study-a", trial_id="trial-a", snapshot=snapshot())
    with pytest.raises(HTTPException) as credentials:
        submit_participant_geometry("session-a", "study-a", "trial-a", body, Response(), control, geometry, "wrong", "http://localhost:5173")
    assert credentials.value.status_code == 401
    control.consents["camera_gaze"] = "declined"
    with pytest.raises(HTTPException) as consent:
        submit_participant_geometry("session-a", "study-a", "trial-a", body, Response(), control, geometry, "credential-a", "http://localhost:5173")
    assert consent.value.status_code == 409
