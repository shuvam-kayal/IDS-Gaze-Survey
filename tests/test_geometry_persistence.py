import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError

from services.gaze_engine.adapter import GazeNormalizationError
from services.gaze_engine.geometry import GeometryScope, validate_geometry_snapshot
from services.telemetry.persistence import (
    GeometrySnapshotRow,
    RecordIdentityConflict,
    TelemetryRepository,
)

DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


def snapshot(session_id: str, study_id: str, version: str, snapshot_id: str, captured_at: str) -> dict:
    return {
        "schema_version": "2.0.0",
        "snapshot_id": snapshot_id,
        "session_id": session_id,
        "study_id": study_id,
        "captured_at": captured_at,
        "aoi_set_version": version,
        "viewport_width_px": 1000,
        "viewport_height_px": 800,
        "scroll_x_px": 0,
        "scroll_y_px": 20,
        "zoom": 1,
        "rectangles": [{
            "aoi_id": "target",
            "left_px": 10,
            "top_px": 20,
            "right_px": 200,
            "bottom_px": 300,
            "priority": 1,
        }],
    }


@pytest.fixture(scope="module")
def repository():
    pytest.importorskip("psycopg", reason="PostgreSQL integration tests require psycopg 3")
    if not DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is required; refusing to use DATABASE_URL or the development database")
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
    except OperationalError as exc:
        pytest.skip(f"PostgreSQL test database unavailable: {exc}")
    return TelemetryRepository(engine)


def test_geometry_validation_requires_v2_and_rejects_bad_scope_or_rectangles():
    scope = GeometryScope("session-1", "study-1", "aoi-1")
    valid = validate_geometry_snapshot(
        snapshot("session-1", "study-1", "aoi-1", "snapshot-1", "2026-01-01T10:00:00Z"),
        scope=scope,
    )
    assert valid["schema_version"] == "2.0.0"
    assert valid["captured_at"] == "2026-01-01T10:00:00Z"
    with pytest.raises(GazeNormalizationError, match="only GeometrySnapshot v2"):
        validate_geometry_snapshot(
            {**valid, "schema_version": "1.0.0"}, scope=scope
        )
    with pytest.raises(GazeNormalizationError, match="scope"):
        validate_geometry_snapshot(
            snapshot("session-other", "study-1", "aoi-1", "snapshot-1", "2026-01-01T10:00:00Z"),
            scope=scope,
        )
    with pytest.raises(GazeNormalizationError, match="bounds"):
        validate_geometry_snapshot(
            {**valid, "rectangles": [{**valid["rectangles"][0], "right_px": 10}]},
            scope=scope,
        )


def test_postgres_geometry_persistence_retry_conflict_order_and_isolation(repository):
    session_id = f"geometry-session-{uuid4()}"
    other_session = f"geometry-other-{uuid4()}"
    scope = GeometryScope(session_id, "study-a", "aoi-a")
    first = snapshot(session_id, "study-a", "aoi-a", "snap-1", "2026-01-01T10:00:00Z")
    later = snapshot(session_id, "study-a", "aoi-a", "snap-2", "2026-01-01T10:00:05Z")
    assert repository.persist_geometry_snapshot(first, trusted_scope=scope) is False
    assert repository.persist_geometry_snapshot(dict(first), trusted_scope=scope) is True
    with pytest.raises(RecordIdentityConflict, match="geometry snapshot identity conflict"):
        repository.persist_geometry_snapshot(
            {**first, "rectangles": [{**first["rectangles"][0], "priority": 9}]},
            trusted_scope=scope,
        )
    repository.persist_geometry_snapshot(later, trusted_scope=scope)
    repository.persist_geometry_snapshot(
        snapshot(other_session, "study-a", "aoi-a", "snap-other", "2026-01-01T10:00:10Z"),
        trusted_scope=GeometryScope(other_session, "study-a", "aoi-a"),
    )
    assert [row["snapshot_id"] for row in repository.list_geometry_snapshots(
        session_id, study_id="study-a", aoi_set_version="aoi-a"
    )] == ["snap-1", "snap-2"]
    assert repository.resolve_geometry_snapshot(
        session_id, study_id="study-a", aoi_set_version="aoi-a",
        at="2026-01-01T10:00:04Z",
    )["snapshot_id"] == "snap-1"
    assert repository.resolve_geometry_snapshot(
        session_id, study_id="study-b", aoi_set_version="aoi-a",
        at="2026-01-01T10:00:10Z",
    ) is None
    assert repository.resolve_geometry_snapshot(
        session_id, study_id="study-a", aoi_set_version="aoi-a",
        at="2025-12-31T23:59:59Z",
    ) is None
    with repository.sessions() as db:
        row = db.get(GeometrySnapshotRow, (session_id, "study-a", "snap-1"))
        assert row is not None
        assert row.provenance == "browser_submitted_untrusted"
        assert row.ingested_at.tzinfo is not None


def test_postgres_geometry_deletion_is_session_scoped_and_idempotent(repository):
    deleted = f"geometry-delete-{uuid4()}"
    kept = f"geometry-keep-{uuid4()}"
    repository.persist_geometry_snapshot(
        snapshot(deleted, "study-a", "aoi-a", "snap-delete", "2026-01-01T10:00:00Z"),
        trusted_scope=GeometryScope(deleted, "study-a", "aoi-a"),
    )
    repository.persist_geometry_snapshot(
        snapshot(kept, "study-a", "aoi-a", "snap-keep", "2026-01-01T10:00:00Z"),
        trusted_scope=GeometryScope(kept, "study-a", "aoi-a"),
    )
    assert repository.delete_session(deleted) is True
    assert repository.delete_session(deleted) is False
    assert repository.list_geometry_snapshots(
        deleted, study_id="study-a", aoi_set_version="aoi-a"
    ) == []
    assert len(repository.list_geometry_snapshots(
        kept, study_id="study-a", aoi_set_version="aoi-a"
    )) == 1
    with repository.sessions() as db:
        assert db.scalar(select(GeometrySnapshotRow).where(GeometrySnapshotRow.session_id == deleted)) is None
