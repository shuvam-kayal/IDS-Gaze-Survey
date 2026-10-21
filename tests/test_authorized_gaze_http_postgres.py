"""PostgreSQL-backed HTTP verification for the additive authorized gaze route.

This test is deliberately opt-in.  It requires TEST_DATABASE_URL so that a
developer cannot accidentally run it against the normal development database.
The control-plane object is a test double, while authentication, context
resolution, geometry lookup, P3 processing, and durable telemetry writes are
exercised through the actual API route and repository.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

import services.api.app as api
from services.gaze_engine.geometry import GeometryScope
from services.telemetry.persistence import TelemetryRepository


class AuthorizedControlDouble:
    def __init__(self, session_id: str, experience_id: str, study_id: str, aoi_set_version: str):
        self.session = {
            "session_id": session_id,
            "experience_id": experience_id,
            "status": "open",
            "withdrawn_at": None,
            "expires_at": "2099-01-01T00:00:00Z",
        }
        self.assignment = {
            "session_id": session_id,
            "experience_id": experience_id,
            "assignments": [{
                "study_id": study_id,
                "config_version": "study-config-1",
                "study_config": {
                    "aoi_set_version": aoi_set_version,
                    "aoi_config": {
                        "config_version": aoi_set_version,
                        "items": [{"aoi_id": "target", "priority": 1}],
                    },
                },
            }],
        }
        self.consent = {
            "consent": [
                {"scope": "research_participation", "decision": "accepted"},
                {"scope": "camera_gaze", "decision": "accepted"},
            ]
        }

    def verify_participant_session(self, *, session_id: str, credential: str):
        if session_id == self.session["session_id"] and credential == "test-credential":
            return self.session
        return None

    def is_origin_authorized(self, experience_id: str, origin: str) -> bool:
        return experience_id == self.session["experience_id"] and origin == "http://localhost:5173"

    def get_assignment(self, session_id: str):
        return self.assignment if session_id == self.session["session_id"] else None

    def participant_consent_state(self, session_id: str):
        return self.consent if session_id == self.session["session_id"] else None


def _event(session_id: str, experience_id: str, study_id: str, event_id: str, event_type: str, occurred_at: str, trial_id: str):
    return {
        "schema_version": "1.0.0",
        "event_id": event_id,
        "experience_id": experience_id,
        "study_ids": [study_id],
        "session_id": session_id,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "payload": {"trial_id": trial_id},
    }


def _geometry(session_id: str, study_id: str, aoi_set_version: str) -> dict:
    return {
        "schema_version": "2.0.0",
        "snapshot_id": "geometry-1",
        "session_id": session_id,
        "study_id": study_id,
        "captured_at": "2026-01-01T10:00:01Z",
        "aoi_set_version": aoi_set_version,
        "viewport_width_px": 1000.0,
        "viewport_height_px": 800.0,
        "scroll_x_px": 0.0,
        "scroll_y_px": 0.0,
        "zoom": 1.0,
        "rectangles": [{
            "aoi_id": "target",
            "left_px": 10.0,
            "top_px": 10.0,
            "right_px": 200.0,
            "bottom_px": 200.0,
            "priority": 1,
        }],
    }


def _sample(sample_id: str = "sample-1") -> dict:
    return {
        "schema_version": "1.0.0",
        "provider": "synthetic-provider",
        "provider_version": "fixture-1",
        "sample_id": sample_id,
        "capture_time_ms": 1000,
        "occurred_at": "2026-01-01T10:00:02Z",
        "x_px": 50.0,
        "y_px": 50.0,
        "valid": True,
        "quality": {"confidence": None, "flags": []},
    }


@pytest.fixture()
def postgres_http_flow(monkeypatch):
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is required for isolated authorized-gaze PostgreSQL verification")
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
    except OperationalError as exc:
        engine.dispose()
        pytest.skip(f"isolated PostgreSQL test database unavailable: {exc}")

    session_id = f"http-authorized-{uuid4()}"
    experience_id = f"experience-{uuid4()}"
    study_id = f"study-{uuid4()}"
    trial_id = f"trial-{uuid4()}"
    aoi_set_version = f"aoi-{uuid4()}"
    repository = TelemetryRepository(engine)
    control = AuthorizedControlDouble(session_id, experience_id, study_id, aoi_set_version)

    repository.ingest(_event(session_id, experience_id, study_id, "start-1", "trial.exposure_started", "2026-01-01T10:00:00Z", trial_id))
    repository.ingest(_event(session_id, experience_id, study_id, "end-1", "trial.exposure_ended", "2026-01-01T10:01:00Z", trial_id))
    repository.persist_server_validated_geometry_snapshot(
        _geometry(session_id, study_id, aoi_set_version),
        trusted_scope=GeometryScope(session_id, study_id, aoi_set_version),
    )

    monkeypatch.setattr(api, "_repository", repository)
    api.app.dependency_overrides[api.get_control_repository] = lambda: control
    try:
        with TestClient(api.app) as client:
            yield {
                "client": client,
                "repository": repository,
                "control": control,
                "session_id": session_id,
                "study_id": study_id,
                "trial_id": trial_id,
            }
    finally:
        api.app.dependency_overrides.pop(api.get_control_repository, None)
        repository.delete_session(session_id)
        engine.dispose()


def test_authorized_http_route_persists_and_retries_against_postgresql(postgres_http_flow):
    flow = postgres_http_flow
    body = {
        "schema_version": "1.1.0",
        "request_id": "request-1",
        "session_id": flow["session_id"],
        "study_id": flow["study_id"],
        "trial_id": flow["trial_id"],
        "provider_samples": [_sample()],
    }
    headers = {"Origin": "http://localhost:5173"}
    cookies = {"ids_participant_session": "test-credential"}

    first = flow["client"].post("/v1/gaze/observations/authorized", json=body, headers=headers, cookies=cookies)
    assert first.status_code == 202, first.text
    assert first.json()["duplicate"] is False
    assert len(flow["repository"].list_gaze_records(flow["session_id"])) == 1
    assert len(flow["repository"].list_feature_records(flow["session_id"], study_id=flow["study_id"])) == 1

    retry = flow["client"].post("/v1/gaze/observations/authorized", json=body, headers=headers, cookies=cookies)
    assert retry.status_code == 200, retry.text
    assert retry.json()["duplicate"] is True
    assert len(flow["repository"].list_gaze_records(flow["session_id"])) == 1
