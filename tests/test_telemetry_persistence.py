import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError

from services.telemetry.persistence import (
    IdentityConflict,
    SessionProcessing,
    TelemetryEvent,
    TelemetryRepository,
)

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://attention:attention@localhost:5432/attention?connect_timeout=5",
    ),
)


def event(session_id: str, event_id: str, occurred_at: str, **changes: object) -> dict:
    value = {
        "schema_version": "1.0.0",
        "event_id": event_id,
        "experience_id": "exp-test",
        "study_ids": ["study-test"],
        "session_id": session_id,
        "event_type": "interaction.click",
        "occurred_at": occurred_at,
        "payload": {"target": "button"},
    }
    value.update(changes)
    return value


@pytest.fixture(scope="module")
def repository():
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
    except OperationalError as exc:
        pytest.skip(f"PostgreSQL test database unavailable: {exc}")
    return TelemetryRepository(engine)


def test_persists_event_and_server_ingestion_time(repository):
    session_id = f"session-{uuid4()}"
    result = repository.ingest(event(session_id, "evt-1", "2026-01-01T10:00:00Z"))
    assert result.duplicate is False
    assert result.ingested_at.tzinfo is not None
    assert len(repository.list_events(session_id)) == 1


def test_exact_retry_returns_original_ingestion_metadata(repository):
    session_id = f"session-{uuid4()}"
    payload = event(session_id, "evt-1", "2026-01-01T10:00:00Z")
    first = repository.ingest(payload)
    second = repository.ingest(dict(payload))
    assert second.duplicate is True
    assert second.ingested_at == first.ingested_at


def test_conflicting_duplicate_is_rejected(repository):
    session_id = f"session-{uuid4()}"
    repository.ingest(event(session_id, "evt-1", "2026-01-01T10:00:00Z"))
    with pytest.raises(IdentityConflict):
        repository.ingest(
            event(session_id, "evt-1", "2026-01-01T10:00:00Z", payload={"target": "other"})
        )


def test_identity_scope_allows_same_event_id_in_other_session(repository):
    event_id = f"evt-{uuid4()}"
    repository.ingest(event(f"session-{uuid4()}", event_id, "2026-01-01T10:00:00Z"))
    second = repository.ingest(event(f"session-{uuid4()}", event_id, "2026-01-01T10:00:00Z"))
    assert second.duplicate is False


def test_retrieval_orders_by_occurred_ingested_then_event_id(repository):
    session_id = f"session-{uuid4()}"
    repository.ingest(event(session_id, "evt-late", "2026-01-01T10:00:02Z"))
    repository.ingest(event(session_id, "evt-early", "2026-01-01T10:00:01Z"))
    assert [row["event_id"] for row in repository.list_events(session_id)] == [
        "evt-early",
        "evt-late",
    ]


def test_session_lifecycle_and_idempotent_deletion(repository):
    session_id = f"session-{uuid4()}"
    repository.ingest(event(session_id, "evt-1", "2026-01-01T10:00:00Z"))
    repository.mark_session_closed(session_id)
    repository.mark_complete(session_id)
    repository.delete_session(session_id)
    repository.delete_session(session_id)
    with repository.sessions() as db:
        assert db.get(SessionProcessing, session_id) is None
        assert (
            db.scalar(select(TelemetryEvent).where(TelemetryEvent.session_id == session_id)) is None
        )


def test_retention_purges_old_events(repository):
    session_id = f"session-{uuid4()}"
    repository.ingest(event(session_id, "evt-1", "2026-01-01T10:00:00Z"))
    with repository.sessions.begin() as db:
        row = db.scalar(
            select(TelemetryEvent).where(
                TelemetryEvent.event_id == "evt-1", TelemetryEvent.session_id == session_id
            )
        )
        row.ingested_at = datetime.now(UTC) - timedelta(days=31)
    assert repository.purge_expired_events(retention_days=30) == 1
