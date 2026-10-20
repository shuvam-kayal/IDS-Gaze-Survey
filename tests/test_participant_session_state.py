from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, inspect
from sqlalchemy.exc import SQLAlchemyError

from services.control_plane.store import (
    ControlPlaneRepository,
    ParticipantConsentRecord,
    ParticipantSessionRecord,
)

DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    os.getenv("DATABASE_URL", "postgresql+psycopg://attention:attention@localhost:5432/attention?connect_timeout=5"),
)


@pytest.fixture(scope="module")
def repository():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        if not {"participant_sessions", "participant_consent_records"}.issubset(set(inspect(engine).get_table_names())):
            pytest.skip("Blocker 3A migration has not been applied to this test database")
    except SQLAlchemyError as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"PostgreSQL unavailable: {exc}")
    repository = ControlPlaneRepository(engine)
    yield repository
    engine.dispose()


def test_session_consent_scopes_and_withdrawal_are_durable_and_idempotent(repository):
    session_id = f"participant-state-{uuid4()}"
    issued = datetime.now(UTC)
    expires = issued + timedelta(hours=1)
    try:
        created = repository.create_participant_session(
            session_id=session_id, experience_id="experience-test", issued_at=issued, expires_at=expires
        )
        state, credential = created
        assert state["status"] == "open"
        assert credential != session_id
        assert "credential_hash" not in state
        assert repository.verify_participant_session(session_id=session_id, credential=credential)["session_id"] == session_id
        assert repository.verify_participant_session(session_id=session_id, credential="wrong") is None
        assert repository.verify_participant_session(session_id=f"other-{session_id}", credential=credential) is None
        assert repository.verify_participant_session(session_id=session_id, credential="") is None
        assert repository.verify_participant_session(session_id=session_id, credential=None) is None
        research = repository.record_participant_consent(
            session_id=session_id, scope="research_participation", decision="accepted",
            policy_version="research-v1", occurred_at=issued + timedelta(seconds=1),
        )
        camera = repository.record_participant_consent(
            session_id=session_id, scope="camera_gaze", decision="declined",
            policy_version="camera-v1", occurred_at=issued + timedelta(seconds=2),
        )
        assert {research["scope"], camera["scope"]} == {"research_participation", "camera_gaze"}
        assert len(repository.participant_consent_state(session_id)["consent"]) == 2
        withdrawn = repository.withdraw_participant_session(session_id, occurred_at=issued + timedelta(seconds=3))
        assert withdrawn["status"] == "withdrawn"
        assert repository.withdraw_participant_session(session_id, occurred_at=issued + timedelta(seconds=3))["status"] == "withdrawn"
        with pytest.raises(ValueError, match="not accepting consent"):
            repository.record_participant_consent(
                session_id=session_id, scope="camera_gaze", decision="accepted",
                policy_version="camera-v2", occurred_at=issued + timedelta(seconds=4),
            )
    finally:
        with repository.sessions.begin() as db:
            db.execute(delete(ParticipantConsentRecord).where(ParticipantConsentRecord.session_id == session_id))
            db.execute(delete(ParticipantSessionRecord).where(ParticipantSessionRecord.session_id == session_id))


def test_expired_server_session_credential_fails_closed(repository):
    session_id = f"participant-expired-{uuid4()}"
    issued = datetime.now(UTC) - timedelta(hours=2)
    expires = issued + timedelta(minutes=1)
    try:
        _, credential = repository.create_participant_session(
            session_id=session_id, experience_id="experience-test", issued_at=issued, expires_at=expires
        )
        assert repository.verify_participant_session(session_id=session_id, credential=credential) is None
    finally:
        with repository.sessions.begin() as db:
            db.execute(delete(ParticipantSessionRecord).where(ParticipantSessionRecord.session_id == session_id))
