from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException, Response

from services.control_plane.participant_auth import require_participant_session
from services.control_plane.router import BootstrapRequest, _timestamp, create_session_bootstrap


class FakeRepository:
    def __init__(self):
        self.calls = []

    def verify_participant_session(self, *, session_id, credential):
        self.calls.append((session_id, credential))
        return {"session_id": session_id, "status": "open"} if credential == "credential-a" and session_id == "session-a" else None


def test_participant_binding_requires_matching_opaque_credential():
    repository = FakeRepository()
    assert require_participant_session("session-a", "credential-a", repository)["session_id"] == "session-a"
    with pytest.raises(HTTPException) as missing:
        require_participant_session("session-a", None, repository)
    assert missing.value.status_code == 401
    with pytest.raises(HTTPException) as wrong_session:
        require_participant_session("session-b", "credential-a", repository)
    assert wrong_session.value.status_code == 401


class BootstrapRepository:
    def __init__(self):
        self.sessions = {}
        self.assignments = {}

    def is_origin_authorized(self, _experience_id, origin):
        return origin == "http://localhost:5173"

    def get_experience(self, _experience_id):
        return {"status": "published", "config_version": "experience-v1"}

    def assign_studies(self, experience_id, session_id, _attributes, _strategy):
        assignments = [{"study_id": "study-a", "config_version": "study-v1", "study_config": {
            "aoi_set_version": "aoi-v1", "question_set_version": "questions-v1", "priority": 0,
        }}]
        self.assignments[session_id] = {"session_id": session_id, "experience_id": experience_id, "assignments": assignments}
        return assignments

    def get_assignment(self, session_id):
        return self.assignments.get(session_id)

    def create_participant_session(self, *, session_id, experience_id, issued_at, expires_at):
        state = {"session_id": session_id, "experience_id": experience_id, "status": "open",
                 "issued_at": issued_at.astimezone(timezone(timedelta(hours=5, minutes=30))),
                 "expires_at": expires_at.astimezone(timezone(timedelta(hours=5, minutes=30)))}
        credential = f"credential-{session_id}"
        self.sessions[credential] = state
        return state, credential

    def find_participant_session_by_credential(self, credential):
        return self.sessions.get(credential)


def test_bootstrap_retry_reuses_same_server_session_and_assignment(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    repository = BootstrapRepository()
    body = BootstrapRequest(experience_id="experience-a")
    first_response = Response()
    first = create_session_bootstrap(body, first_response, repository, "http://localhost:5173", None)
    cookie = first_response.headers["set-cookie"].split(";", 1)[0].split("=", 1)[1]
    second_response = Response()
    second = create_session_bootstrap(body, second_response, repository, "http://localhost:5173", cookie)
    assert second.session_id == first.session_id
    assert second.issued_at == first.issued_at
    assert "set-cookie" not in second_response.headers


def test_api_timestamps_are_normalized_to_utc():
    local_time = datetime(2026, 10, 29, 18, 40, 59, 812535, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert _timestamp(local_time) == "2026-10-29T13:10:59.812535Z"
