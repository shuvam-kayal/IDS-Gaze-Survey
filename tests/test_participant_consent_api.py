import pytest
from fastapi import HTTPException, Response
from pydantic import ValidationError

from services.control_plane.router import (
    ParticipantConsentRequest,
    ParticipantWithdrawalRequest,
    record_participant_consent,
    withdraw_participant_session,
)


class ConsentRepository:
    def __init__(self):
        self.sessions = {
            "session-a": {"session_id": "session-a", "experience_id": "experience-a", "status": "open", "withdrawn_at": None},
            "session-b": {"session_id": "session-b", "experience_id": "experience-a", "status": "open", "withdrawn_at": None},
        }
        self.credentials = {"credential-a": "session-a", "credential-b": "session-b"}
        self.consents = {}

    def verify_participant_session(self, *, session_id, credential):
        session = self.sessions.get(session_id)
        if self.credentials.get(credential) != session_id or not session or session["status"] != "open":
            return None
        return session

    def is_origin_authorized(self, experience_id, origin):
        return experience_id == "experience-a" and origin == "http://localhost:5173"

    def participant_consent_state(self, session_id):
        return {"consent": [dict(value) for (sid, _), value in self.consents.items() if sid == session_id]}

    def record_participant_consent(self, *, session_id, scope, decision, policy_version, occurred_at):
        key = (session_id, scope)
        value = {"scope": scope, "decision": decision, "policy_version": policy_version, "occurred_at": occurred_at, "duplicate": False}
        if scope == "camera_gaze" and self.consents.get((session_id, "research_participation"), {}).get("decision") != "accepted":
            raise ValueError("research participation consent is required before camera consent")
        existing = self.consents.get(key)
        if existing:
            if any(existing[field] != value[field] for field in ("decision", "policy_version", "occurred_at")):
                raise ValueError("participant consent decision conflict")
            return {**existing, "duplicate": True}
        self.consents[key] = value
        return value

    def withdraw_participant_session(self, session_id, *, occurred_at):
        session = self.sessions[session_id]
        session.update(status="withdrawn", withdrawn_at=occurred_at)
        return session


def consent(scope="research_participation", decision="accepted"):
    return ParticipantConsentRequest(
        scope=scope, decision=decision, policy_version="policy-v1", occurred_at="2026-10-20T10:00:00Z"
    )


def test_consent_requires_bound_credential_and_exact_origin():
    repository = ConsentRepository()
    result = record_participant_consent("session-a", consent(), Response(), repository, "credential-a", "http://localhost:5173")
    assert result.duplicate is False
    with pytest.raises(HTTPException) as wrong:
        record_participant_consent("session-a", consent(), Response(), repository, "credential-b", "http://localhost:5173")
    assert wrong.value.status_code == 401
    with pytest.raises(HTTPException) as csrf:
        record_participant_consent("session-a", consent(), Response(), repository, "credential-a", "https://evil.example")
    assert csrf.value.status_code == 403


def test_consent_scopes_are_separate_and_exact_retry_is_idempotent():
    repository = ConsentRepository()
    first = record_participant_consent("session-a", consent(), Response(), repository, "credential-a", "http://localhost:5173")
    retry = record_participant_consent("session-a", consent(), Response(), repository, "credential-a", "http://localhost:5173")
    assert first.occurred_at == retry.occurred_at
    assert retry.duplicate is True
    camera = record_participant_consent("session-a", consent("camera_gaze"), Response(), repository, "credential-a", "http://localhost:5173")
    assert camera.scope == "camera_gaze"
    with pytest.raises(HTTPException) as conflict:
        record_participant_consent("session-a", consent(decision="declined"), Response(), repository, "credential-a", "http://localhost:5173")
    assert conflict.value.status_code == 409


def test_camera_consent_requires_research_consent_and_body_is_strict():
    repository = ConsentRepository()
    with pytest.raises(HTTPException) as missing:
        record_participant_consent("session-a", consent("camera_gaze"), Response(), repository, "credential-a", "http://localhost:5173")
    assert missing.value.status_code == 409
    with pytest.raises(ValidationError):
        ParticipantConsentRequest(**{**consent().model_dump(), "unexpected": True})


def test_withdrawal_is_immediate_and_subsequent_authentication_fails_closed():
    repository = ConsentRepository()
    result = withdraw_participant_session(
        "session-a", ParticipantWithdrawalRequest(occurred_at="2026-10-20T10:01:00Z"), Response(), repository,
        "credential-a", "http://localhost:5173",
    )
    assert result.status == "withdrawn"
    with pytest.raises(HTTPException) as after:
        withdraw_participant_session(
            "session-a", ParticipantWithdrawalRequest(occurred_at="2026-10-20T10:02:00Z"), Response(), repository,
            "credential-a", "http://localhost:5173",
        )
    assert after.value.status_code == 401


def test_missing_or_malformed_credentials_and_timestamps_fail_closed():
    repository = ConsentRepository()
    with pytest.raises(HTTPException) as missing:
        record_participant_consent("session-a", consent(), Response(), repository, None, "http://localhost:5173")
    assert missing.value.status_code == 401
    with pytest.raises(HTTPException) as malformed:
        record_participant_consent(
            "session-a", ParticipantConsentRequest(scope="research_participation", decision="accepted", policy_version="v1", occurred_at="not-a-time"),
            Response(), repository, "credential-a", "http://localhost:5173",
        )
    assert malformed.value.status_code == 422
