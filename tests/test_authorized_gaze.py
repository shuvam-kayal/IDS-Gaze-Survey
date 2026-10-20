import json
import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from services.feature_engine.authorized_gaze import (
    AuthorizedGazeContext,
    process_authorized_gaze,
)
from services.gaze_engine.context import TrialObservationContext
from services.telemetry.persistence import TelemetryRepository

SESSION = "session-authorized-1"
STUDY = "study-authorized-1"
TRIAL = "trial-authorized-1"
AOI_VERSION = "aoi-authorized-1"
START = "2026-01-01T10:00:00Z"
END = "2026-01-01T10:00:10Z"


def sample(sample_id: str, offset_ms: int, *, x: float = 25) -> dict:
    occurred = datetime(2026, 1, 1, 10, 0, tzinfo=UTC) + timedelta(milliseconds=offset_ms)
    return {
        "schema_version": "1.0.0",
        "provider": "synthetic-provider",
        "provider_version": "fixture-1",
        "sample_id": sample_id,
        "capture_time_ms": offset_ms,
        "occurred_at": occurred.isoformat().replace("+00:00", "Z"),
        "x_px": x,
        "y_px": 25,
        "valid": True,
        "quality": {"confidence": 0.9, "flags": []},
    }


def context(*, session_id: str = SESSION, **changes) -> AuthorizedGazeContext:
    observation = TrialObservationContext(
        session_id, STUDY, TRIAL, AOI_VERSION, START, END
    )
    values = {
        "experience_id": "experience-authorized-1",
        "session_id": session_id,
        "study_id": STUDY,
        "trial_id": TRIAL,
        "aoi_set_version": AOI_VERSION,
        "observation_context": observation,
        "geometry_snapshots": [
            {
                "schema_version": "2.0.0",
                "snapshot_id": "geometry-authorized-1",
                "session_id": session_id,
                "study_id": STUDY,
                "captured_at": "2026-01-01T09:59:00Z",
                "aoi_set_version": AOI_VERSION,
                "viewport_width_px": 100,
                "viewport_height_px": 100,
                "scroll_x_px": 0,
                "scroll_y_px": 0,
                "zoom": 1,
                "rectangles": [{
                    "aoi_id": "target",
                    "left_px": 0,
                    "top_px": 0,
                    "right_px": 50,
                    "bottom_px": 50,
                    "priority": 1,
                }],
            }
        ],
        "events": [{
            "schema_version": "1.0.0",
            "event_id": "start-authorized-1",
            "experience_id": "experience-authorized-1",
            "study_ids": [STUDY],
            "session_id": session_id,
            "event_type": "trial.exposure_started",
            "occurred_at": START,
            "payload": {"trial_id": TRIAL},
        }],
        "start_event": {
            "schema_version": "1.0.0",
            "event_id": "start-authorized-1",
            "experience_id": "experience-authorized-1",
            "study_ids": [STUDY],
            "session_id": session_id,
            "event_type": "trial.exposure_started",
            "occurred_at": START,
            "payload": {"trial_id": TRIAL},
        },
        "requested_aoi_id": "target",
        "viewport_width_px": 100,
        "viewport_height_px": 100,
    }
    values.update(changes)
    return AuthorizedGazeContext(**values)


class FakeRepository:
    def __init__(self, *, fail_features: bool = False):
        self.associations = {}
        self.features = {}
        self.fail_features = fail_features

    def persist_gaze_association(self, association):
        key = (association["association_id"], association["session_id"])
        encoded = json.dumps(association, sort_keys=True)
        if key in self.associations and self.associations[key] != encoded:
            raise ValueError("gaze association identity conflict")
        self.associations[key] = encoded
        return association["gaze_records"]

    def persist_feature_record(self, record):
        if self.fail_features:
            raise RuntimeError("feature persistence failed")
        key = record["feature_record_id"]
        encoded = json.dumps(record, sort_keys=True)
        if key in self.features and self.features[key] != encoded:
            raise ValueError("feature record identity conflict")
        self.features[key] = encoded
        return record

    def gaze_association_exists(self, association_id, session_id):
        return (association_id, session_id) in self.associations

    def feature_record_exists(self, feature_record_id):
        return feature_record_id in self.features


@pytest.fixture(scope="module")
def postgres_repository():
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is required; refusing to use DATABASE_URL or the development database")
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
    except OperationalError as exc:
        pytest.skip(f"PostgreSQL test database unavailable: {exc}")
    return TelemetryRepository(engine)


def test_valid_authorized_context_reaches_existing_pipeline_and_persistence():
    repository = FakeRepository()
    result = process_authorized_gaze(
        [sample("sample-0", 0), sample("sample-1", 100), sample("sample-2", 200)],
        context=context(),
        repository=repository,
    )

    assert result.feature_record["modality"] == "gaze_and_non_gaze"
    assert len(result.gaze_records) == 3
    assert len(repository.associations) == 1
    assert len(repository.features) == 1
    assert result.duplicate is False


def test_context_identity_must_match_observation_context():
    mismatched = context(study_id="study-other")
    with pytest.raises(ValueError, match="does not match observation context"):
        process_authorized_gaze([sample("sample-0", 0)], context=mismatched, repository=FakeRepository())


def test_invalid_provider_sample_is_rejected_before_persistence():
    with pytest.raises(ValueError, match="inside the viewport"):
        process_authorized_gaze(
            [sample("sample-0", 0, x=101)], context=context(), repository=FakeRepository()
        )


def test_association_window_validation_rejects_sample_at_end_boundary():
    with pytest.raises(ValueError, match="outside the observation window"):
        process_authorized_gaze(
            [sample("sample-end", 10_000)], context=context(), repository=FakeRepository()
        )


def test_exact_retry_is_deterministic_and_idempotent():
    repository = FakeRepository()
    samples = [sample("sample-0", 0), sample("sample-1", 100), sample("sample-2", 200)]
    first = process_authorized_gaze(samples, context=context(), repository=repository)
    second = process_authorized_gaze(list(reversed(samples)), context=context(), repository=repository)

    assert first.feature_record == second.feature_record
    assert first.gaze_records == second.gaze_records
    assert len(repository.associations) == 1
    assert len(repository.features) == 1
    assert second.duplicate is True


def test_unavailable_gaze_preserves_non_gaze_feature_record_without_association():
    unavailable = context(
        gaze_available=False,
        gaze_missingness="gaze.permission_denied",
        start_event=None,
    )
    result = process_authorized_gaze([], context=unavailable, repository=FakeRepository())

    assert result.feature_record["modality"] == "non_gaze_only"
    assert "gaze.permission_denied" in result.feature_record["quality"]["missingness"]
    assert result.association is None


def test_feature_write_failure_does_not_claim_success():
    repository = FakeRepository(fail_features=True)
    with pytest.raises(RuntimeError, match="feature persistence failed"):
        process_authorized_gaze([sample("sample-0", 0)], context=context(), repository=repository)
    assert repository.associations
    assert not repository.features


def test_retry_reconciles_association_when_feature_write_failed():
    repository = FakeRepository(fail_features=True)
    samples = [sample("sample-0", 0), sample("sample-1", 100), sample("sample-2", 200)]
    with pytest.raises(RuntimeError, match="feature persistence failed"):
        process_authorized_gaze(samples, context=context(), repository=repository)

    repository.fail_features = False
    recovered = process_authorized_gaze(samples, context=context(), repository=repository)
    retried = process_authorized_gaze(samples, context=context(), repository=repository)

    assert recovered.duplicate is False
    assert retried.duplicate is True
    assert len(repository.associations) == 1
    assert len(repository.features) == 1


def test_postgres_handler_persists_and_retries_with_real_repository(postgres_repository):
    session_id = "session-authorized-postgres-" + datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    samples = [sample("sample-0", 0), sample("sample-1", 100), sample("sample-2", 200)]
    first = process_authorized_gaze(
        samples, context=context(session_id=session_id), repository=postgres_repository
    )
    retry = process_authorized_gaze(
        list(reversed(samples)), context=context(session_id=session_id), repository=postgres_repository
    )

    assert first.duplicate is False
    assert retry.duplicate is True
    assert [row["sample_id"] for row in postgres_repository.list_gaze_records(session_id)] == [
        "sample-0", "sample-1", "sample-2"
    ]
    assert len(postgres_repository.list_feature_records(session_id)) == 1
    assert postgres_repository.delete_session(session_id) is True
