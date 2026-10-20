import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError

from services.telemetry.persistence import (
    FeatureRecordRow,
    GazeObservationAssociationRow,
    GazeRecordRow,
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


def gaze_record(session_id: str, sample_id: str, occurred_at: str, *, x: float = 0.25) -> dict:
    return {
        "schema_version": "1.0.0",
        "sample_id": sample_id,
        "session_id": session_id,
        "occurred_at": occurred_at,
        "coordinate_space": "viewport_normalized",
        "x_normalized": x,
        "y_normalized": 0.5,
        "confidence": None,
        "valid": True,
        "calibration_status": "not_required",
        "quality_flags": ["gaze.calibration_unverified"],
    }


def association(session_id: str, association_id: str, records: list[dict]) -> dict:
    return {
        "schema_version": "1.0.0",
        "association_id": association_id,
        "session_id": session_id,
        "study_id": "study-test",
        "trial_id": "trial-test",
        "aoi_set_version": "aoi-test",
        "window_start": "2026-01-01T10:00:00Z",
        "window_end": "2026-01-01T10:00:10Z",
        "gaze_records": records,
    }


def feature_record(session_id: str, feature_record_id: str, *, modality: str = "non_gaze_only") -> dict:
    return {
        "schema_version": "1.0.0",
        "feature_record_id": feature_record_id,
        "experience_id": "exp-test",
        "study_id": "study-test",
        "session_id": session_id,
        "feature_set_version": "1.0.0",
        "config_version": None,
        "aoi_set_version": None,
        "modality": modality,
        "window": None,
        "features": {"interaction.click_count": 0},
        "quality": {"gaze_available": False, "missingness": ["gaze.no_samples"], "calibration_status": None},
        "source_event_count": 0,
    }


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


def test_deletion_is_session_scoped_and_handles_processing_only_sessions(repository):
    deleted_session = f"session-delete-{uuid4()}"
    other_session = f"session-keep-{uuid4()}"
    repository.ingest(event(deleted_session, "evt-delete", "2026-01-01T10:00:00Z"))
    repository.ingest(event(other_session, "evt-keep", "2026-01-01T10:00:00Z"))

    assert repository.delete_session(deleted_session) is True
    assert repository.delete_session(deleted_session) is False
    assert [row["event_id"] for row in repository.list_events(other_session)] == ["evt-keep"]

    processing_only_session = f"session-processing-only-{uuid4()}"
    repository.mark_session_closed(processing_only_session, partial=True)
    assert repository.delete_session(processing_only_session) is True
    assert repository.delete_session(processing_only_session) is False


def test_gaze_and_feature_records_round_trip_with_deterministic_order(repository):
    session_id = f"session-derived-{uuid4()}"
    records = [
        gaze_record(session_id, "sample-2", "2026-01-01T10:00:02Z"),
        gaze_record(session_id, "sample-1", "2026-01-01T10:00:01Z"),
    ]
    repository.persist_gaze_association(association(session_id, "assoc-1", records))
    # FeatureRecord IDs are globally unique in the durable table. Keep the
    # test identity stable for retries while avoiding collisions with other
    # sessions in the shared PostgreSQL test database.
    persisted_feature = feature_record(session_id, f"feature-{session_id}")
    assert repository.persist_feature_record(persisted_feature) == persisted_feature
    assert [row["sample_id"] for row in repository.list_gaze_records(session_id)] == [
        "sample-1", "sample-2"
    ]
    assert repository.list_feature_records(session_id) == [persisted_feature]


def test_derived_record_retries_are_idempotent_and_conflicts_rejected(repository):
    session_id = f"session-derived-retry-{uuid4()}"
    record = gaze_record(session_id, "sample-1", "2026-01-01T10:00:01Z")
    payload = association(session_id, "assoc-1", [record])
    repository.persist_gaze_association(payload)
    repository.persist_gaze_association(dict(payload))
    with pytest.raises(ValueError, match="gaze sample identity conflict"):
        repository.persist_gaze_association(
            association(session_id, "assoc-2", [gaze_record(session_id, "sample-1", "2026-01-01T10:00:01Z", x=0.75)])
        )

    feature = feature_record(session_id, f"feature-{session_id}")
    repository.persist_feature_record(feature)
    assert repository.persist_feature_record(dict(feature)) == feature
    conflicting = {**feature, "features": {"interaction.click_count": 99}}
    with pytest.raises(ValueError, match="feature record identity conflict"):
        repository.persist_feature_record(conflicting)


def test_derived_persistence_rolls_back_on_conflict(repository):
    session_id = f"session-derived-rollback-{uuid4()}"
    existing = gaze_record(session_id, "sample-existing", "2026-01-01T10:00:01Z")
    repository.persist_gaze_association(association(session_id, "assoc-existing", [existing]))
    new_record = gaze_record(session_id, "sample-new", "2026-01-01T10:00:02Z")
    with pytest.raises(ValueError, match="gaze sample identity conflict"):
        repository.persist_gaze_association(
            association(session_id, "assoc-failing", [new_record, {**existing, "x_normalized": 0.9}])
        )
    assert [row["sample_id"] for row in repository.list_gaze_records(session_id)] == ["sample-existing"]


def test_session_deletion_removes_derived_records_without_affecting_other_sessions(repository):
    deleted_session = f"session-derived-delete-{uuid4()}"
    other_session = f"session-derived-keep-{uuid4()}"
    repository.persist_gaze_association(
        association(deleted_session, "assoc-delete", [gaze_record(deleted_session, "sample-1", "2026-01-01T10:00:01Z")])
    )
    repository.persist_feature_record(feature_record(deleted_session, f"feature-{deleted_session}"))
    repository.persist_gaze_association(
        association(other_session, "assoc-keep", [gaze_record(other_session, "sample-1", "2026-01-01T10:00:01Z")])
    )
    repository.persist_feature_record(feature_record(other_session, f"feature-{other_session}"))

    assert repository.delete_session(deleted_session) is True
    assert repository.delete_session(deleted_session) is False
    assert repository.list_gaze_records(deleted_session) == []
    assert repository.list_feature_records(deleted_session) == []
    with repository.sessions() as db:
        assert db.scalar(select(GazeRecordRow).where(GazeRecordRow.session_id == deleted_session)) is None
        assert db.scalar(select(GazeObservationAssociationRow).where(GazeObservationAssociationRow.session_id == deleted_session)) is None
        assert db.scalar(select(FeatureRecordRow).where(FeatureRecordRow.session_id == deleted_session)) is None
    assert len(repository.list_gaze_records(other_session)) == 1
    assert len(repository.list_feature_records(other_session)) == 1


def test_late_event_reopens_completed_processing_scope(repository):
    session_id = f"session-{uuid4()}"
    repository.ingest(event(session_id, "evt-close", "2026-01-01T10:00:02Z"))
    repository.mark_session_closed(session_id)
    repository.mark_complete(session_id)
    repository.ingest(event(session_id, "evt-late", "2026-01-01T10:00:01Z"))
    with repository.sessions() as db:
        processing = db.get(SessionProcessing, session_id)
        assert processing is not None
        assert processing.state == "open"


def test_retention_purges_old_events(repository):
    session_id = f"session-closed-{uuid4()}"
    open_session_id = f"session-open-{uuid4()}"
    repository.ingest(event(session_id, "evt-1", "2026-01-01T10:00:00Z"))
    repository.ingest(event(open_session_id, "evt-open", "2026-01-01T10:00:00Z"))
    reference_time = datetime(2026, 2, 1, tzinfo=UTC)
    with repository.sessions.begin() as db:
        row = db.scalar(
            select(TelemetryEvent).where(
                TelemetryEvent.event_id == "evt-1", TelemetryEvent.session_id == session_id
            )
        )
        row.ingested_at = reference_time
        db.get(SessionProcessing, session_id).closed_at = reference_time - timedelta(days=31)
        open_row = db.get(SessionProcessing, open_session_id)
        open_row.closed_at = None
        db.scalar(
            select(TelemetryEvent).where(
                TelemetryEvent.event_id == "evt-open", TelemetryEvent.session_id == open_session_id
            )
        ).ingested_at = reference_time - timedelta(days=31)
    assert repository.purge_expired_events(now=reference_time, retention_days=30) == 1
    assert repository.list_events(session_id) == []
    with repository.sessions() as db:
        assert db.get(SessionProcessing, session_id) is None
    assert [row["event_id"] for row in repository.list_events(open_session_id)] == ["evt-open"]


def test_retention_keeps_event_at_exact_closure_boundary(repository):
    session_id = f"session-boundary-{uuid4()}"
    repository.ingest(event(session_id, "evt-boundary", "2026-01-01T10:00:00Z"))
    reference_time = datetime(2026, 2, 1, tzinfo=UTC)
    with repository.sessions.begin() as db:
        processing = db.get(SessionProcessing, session_id)
        processing.closed_at = reference_time - timedelta(days=30)
        db.scalar(
            select(TelemetryEvent).where(
                TelemetryEvent.event_id == "evt-boundary", TelemetryEvent.session_id == session_id
            )
        ).ingested_at = reference_time - timedelta(days=31)
    assert repository.purge_expired_events(now=reference_time, retention_days=30) == 0
    assert len(repository.list_events(session_id)) == 1


@pytest.mark.parametrize("retention_days", [0, -1])
def test_retention_rejects_non_positive_period(repository, retention_days):
    with pytest.raises(ValueError, match="retention_days must be positive"):
        repository.purge_expired_events(retention_days=retention_days)
