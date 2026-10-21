from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response

import services.api.app as api
from services.feature_engine.trusted_context import TrustedGazeContextProvider
from services.gaze_engine.adapter import GazeNormalizationError

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


def event(event_id, event_type, occurred_at, trial_id="trial-a"):
    return {
        "schema_version": "1.0.0", "event_id": event_id, "experience_id": "experience-a",
        "study_ids": ["study-a"], "session_id": "session-a", "event_type": event_type,
        "occurred_at": occurred_at, "payload": {"trial_id": trial_id},
    }


def geometry(provenance="server_validated", session_id="session-a", study_id="study-a", version="aoi-v1"):
    return {
        "schema_version": "2.0.0", "snapshot_id": "geometry-1", "session_id": session_id,
        "study_id": study_id, "captured_at": "2026-10-20T10:00:01Z", "aoi_set_version": version,
        "viewport_width_px": 1000.0, "viewport_height_px": 800.0, "scroll_x_px": 0.0,
        "scroll_y_px": 0.0, "zoom": 1.0,
        "rectangles": [{"aoi_id": "target", "left_px": 10.0, "top_px": 10.0, "right_px": 100.0, "bottom_px": 100.0, "priority": 1}],
        "provenance": provenance,
    }


def provider_samples(timestamp="2026-10-20T10:00:02Z"):
    return [{
        "schema_version": "1.0.0", "provider": "synthetic-provider", "provider_version": "fixture-1",
        "sample_id": "sample-1", "capture_time_ms": 1, "occurred_at": timestamp,
        "x_px": 50, "y_px": 50, "valid": True, "quality": {"confidence": None, "flags": []},
    }]


class Control:
    def __init__(self):
        self.session = dict(SESSION)
        self.assignment = ASSIGNMENT
        self.consents = {"research_participation": "accepted", "camera_gaze": "accepted"}

    def verify_participant_session(self, *, session_id, credential):
        return self.session if session_id == "session-a" and credential == "credential-a" else None

    def is_origin_authorized(self, experience_id, origin):
        return experience_id == "experience-a" and origin == "http://localhost:5173"

    def get_assignment(self, _session_id):
        return self.assignment

    def participant_consent_state(self, _session_id):
        return {"consent": [{"scope": scope, "decision": decision} for scope, decision in self.consents.items()]}


class Telemetry:
    def __init__(self, rows=None, events=None):
        self.rows = rows if rows is not None else [geometry()]
        self.events = events if events is not None else [
            event("start-1", "trial.exposure_started", "2026-10-20T10:00:00Z"),
            event("end-1", "trial.exposure_ended", "2026-10-20T10:01:00Z"),
        ]

    def list_events(self, _session_id, *, study_id=None):
        return self.events if study_id == "study-a" else []

    def list_geometry_snapshots(self, _session_id, *, study_id, aoi_set_version, at, provenance=None):
        return [
            {key: value for key, value in row.items() if key != "provenance"}
            for row in self.rows
            if row["study_id"] == study_id and row["aoi_set_version"] == aoi_set_version
            and (provenance is None or row.get("provenance") == provenance)
        ]


def request(**changes):
    value = {
        "schema_version": "1.1.0", "request_id": "request-1", "session_id": "session-a",
        "study_id": "study-a", "trial_id": "trial-a", "provider_samples": provider_samples(),
    }
    value.update(changes)
    return value


def make_provider(control=None, telemetry=None, session=None):
    return TrustedGazeContextProvider(
        control_repository=control or Control(), telemetry_repository=telemetry or Telemetry(),
        participant_session=session or SESSION,
    )


def test_provider_resolves_only_server_owned_context_and_validates_samples():
    context = make_provider().resolve(request())
    assert (context.session_id, context.study_id, context.trial_id) == ("session-a", "study-a", "trial-a")
    assert context.aoi_set_version == "aoi-v1"
    assert "provenance" not in context.geometry_snapshots[0]
    assert context.observation_context.window_start == "2026-10-20T10:00:00Z"


@pytest.mark.parametrize("session", [
    {**SESSION, "status": "withdrawn", "withdrawn_at": "2026-10-20T10:00:00Z"},
    {**SESSION, "status": "closed"},
    {**SESSION, "expires_at": "2026-10-20T09:00:00Z"},
])
def test_provider_rejects_terminal_or_expired_sessions(session):
    with pytest.raises(GazeNormalizationError, match="session"):
        make_provider(session=session).resolve(request())


def test_provider_rejects_missing_consent_assignment_and_cross_session_selector():
    control = Control()
    control.consents["camera_gaze"] = "declined"
    with pytest.raises(GazeNormalizationError, match="camera/gaze"):
        make_provider(control=control).resolve(request())
    control = Control()
    control.assignment = {**ASSIGNMENT, "assignments": []}
    with pytest.raises(GazeNormalizationError, match="unambiguously"):
        make_provider(control=control).resolve(request())
    with pytest.raises(GazeNormalizationError, match="does not match"):
        make_provider().resolve(request(session_id="session-other"))


@pytest.mark.parametrize("rows, events, expected", [
    ([], None, "no server-validated geometry"),
    ([geometry(provenance="browser_submitted_untrusted")], None, "no server-validated geometry"),
    (None, [], "observation_start_missing"),
])
def test_provider_rejects_missing_untrusted_geometry_or_lifecycle(rows, events, expected):
    telemetry = Telemetry(rows=[] if rows is None else rows, events=events if events is not None else Telemetry().events)
    with pytest.raises(GazeNormalizationError, match=expected):
        make_provider(telemetry=telemetry).resolve(request())


def test_provider_rejects_samples_outside_window_and_client_trusted_fields():
    with pytest.raises(GazeNormalizationError, match="outside"):
        make_provider().resolve(request(provider_samples=provider_samples("2026-10-20T10:01:00Z")))
    with pytest.raises(GazeNormalizationError, match="invalid fields"):
        make_provider().resolve(request(provenance="server_validated"))


def test_api_handoff_verifies_cookie_before_constructing_provider(monkeypatch):
    control = Control()
    telemetry = Telemetry()
    api._repository = telemetry
    monkeypatch.setattr(api, "process_authorized_gaze", lambda samples, *, context, repository: SimpleNamespace(
        duplicate=False, feature_record={"feature_record_id": "feature-1"}, gaze_records=[{"sample_id": "sample-1"}],
    ))
    body = api.AuthorizedGazeObservationRequest.model_validate(request())
    response = api.ingest_authorized_gaze_observation(body, Response(), control, "credential-a", "http://localhost:5173")
    assert response.status_code == 202
    with pytest.raises(HTTPException) as unauthorized:
        api.ingest_authorized_gaze_observation(body, Response(), control, None, "http://localhost:5173")
    assert unauthorized.value.status_code == 401
    api._repository = None
