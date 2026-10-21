from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from services.analytics.feature_records import TelemetryFeatureRecordProvider
from services.analytics.integration import create_analytics_router
from services.feature_engine.authorized_gaze import (
    AuthorizedGazeContext,
    process_authorized_gaze,
)
from services.gaze_engine.context import TrialObservationContext
from services.telemetry.persistence import TelemetryRepository


class MemoryAnalysisRepository:
    """Keep this test focused on the real P3 persistence-to-P4 read boundary."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.requests: dict[tuple[str, str], dict] = {}

    def save(self, request: dict, result: dict) -> dict:
        self.rows[result["analysis_id"]] = result
        self.requests[(request["analysis_request_id"], request["study_id"])] = result
        return result

    def get_by_request(self, request_id: str, study_id: str) -> dict | None:
        return self.requests.get((request_id, study_id))

    def get(self, analysis_id: str) -> dict | None:
        return self.rows.get(analysis_id)

    def update(self, result: dict) -> dict:
        self.rows[result["analysis_id"]] = result
        return result

    def list_page(self, study_id: str, limit: int, cursor: str | None) -> dict:
        results = [row for row in self.rows.values() if row["study_id"] == study_id][:limit]
        return {"results": results, "next_cursor": None, "limit": limit}


def test_p3_postgres_feature_record_is_read_and_analyzed_by_p4(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = os.environ.get(
        "TEST_DATABASE_URL",
        os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://attention:attention@localhost:5432/attention?connect_timeout=5",
        ),
    )
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
    except OperationalError as exc:
        engine.dispose()
        pytest.skip(f"PostgreSQL test database unavailable: {exc}")

    from services.api import app as p3_api

    session_id = f"session-p3-p4-postgres-{uuid4()}"
    study_id = f"study-p3-p4-postgres-{uuid4()}"
    trial_id = f"trial-p3-p4-postgres-{uuid4()}"
    request_id = f"request-p3-p4-postgres-{uuid4()}"
    start_at = "2026-01-01T10:00:00Z"
    end_at = "2026-01-01T10:00:10Z"
    aoi_set_version = "aoi-p3-p4-postgres-v1"
    observation_context = TrialObservationContext(
        session_id, study_id, trial_id, aoi_set_version, start_at, end_at,
    )
    event = {
        "schema_version": "1.0.0",
        "event_id": f"event-{request_id}",
        "experience_id": f"experience-{request_id}",
        "study_ids": [study_id],
        "session_id": session_id,
        "event_type": "interaction.click",
        "occurred_at": "2026-01-01T10:00:01Z",
        "payload": {},
    }
    start_event = {
        **event,
        "event_id": f"start-{request_id}",
        "event_type": "trial.exposure_started",
        "occurred_at": start_at,
        "payload": {"trial_id": trial_id},
    }
    geometry = {
        "schema_version": "2.0.0",
        "snapshot_id": f"geometry-{request_id}",
        "session_id": session_id,
        "study_id": study_id,
        "captured_at": "2026-01-01T09:59:00Z",
        "aoi_set_version": aoi_set_version,
        "viewport_width_px": 1024,
        "viewport_height_px": 768,
        "scroll_x_px": 0,
        "scroll_y_px": 0,
        "zoom": 1,
        "rectangles": [{
            "aoi_id": "hero",
            "left_px": 0,
            "top_px": 0,
            "right_px": 1024,
            "bottom_px": 768,
            "priority": 1,
        }],
    }
    trusted_context = AuthorizedGazeContext(
        experience_id=event["experience_id"],
        session_id=session_id,
        study_id=study_id,
        trial_id=trial_id,
        aoi_set_version=aoi_set_version,
        observation_context=observation_context,
        geometry_snapshots=[geometry],
        events=[event],
        start_event=start_event,
        requested_aoi_id="hero",
        viewport_width_px=1024,
        viewport_height_px=768,
    )

    class TrustedContextProvider:
        def resolve(self, request_body: dict) -> AuthorizedGazeContext:
            assert request_body["session_id"] == session_id
            return trusted_context

    telemetry_repository = TelemetryRepository(engine)
    monkeypatch.setattr(p3_api, "_repository", telemetry_repository)
    monkeypatch.setattr(p3_api, "_gaze_context_provider", TrustedContextProvider())
    feature_provider = TelemetryFeatureRecordProvider(
        telemetry_repository,
        session_ids_for_study=lambda requested_study: [session_id]
        if requested_study == study_id else [],
    )
    analysis_repository = MemoryAnalysisRepository()

    app = FastAPI()
    app.add_api_route(
        "/v1/gaze/observations", p3_api.ingest_gaze_observation, methods=["POST"],
    )
    app.include_router(create_analytics_router(
        get_feature_provider=lambda: feature_provider,
        get_repository=lambda: analysis_repository,
        get_study_authorizer=lambda: lambda requested_study: requested_study == study_id,
    ))

    try:
        sample_template = json_load_fixture("fixtures/gaze/provider-sample-valid.json")
        provider_samples = [
            {
                **sample_template,
                "sample_id": f"sample-{request_id}-{index}",
                "capture_time_ms": offset,
                "occurred_at": f"2026-01-01T10:00:{offset // 1000:02d}.{offset % 1000:03d}Z",
            }
            for index, offset in enumerate((1000, 1100, 1200))
        ]
        client = TestClient(app)
        p3_response = client.post("/v1/gaze/observations", json={
            "schema_version": "1.0.0",
            "request_id": request_id,
            "session_id": session_id,
            "provider_samples": provider_samples,
        })
        assert p3_response.status_code == 202, p3_response.text
        feature_record_id = p3_response.json()["feature_record_id"]

        # P3 retries must remain idempotent across the durable boundary.
        retry_response = client.post("/v1/gaze/observations", json={
            "schema_version": "1.0.0",
            "request_id": request_id,
            "session_id": session_id,
            "provider_samples": provider_samples,
        })
        assert retry_response.status_code == 200, retry_response.text
        assert retry_response.json()["feature_record_id"] == feature_record_id

        persisted_records = telemetry_repository.list_feature_records(
            session_id, study_id=study_id,
        )
        assert len(persisted_records) == 1
        assert persisted_records[0]["feature_record_id"] == feature_record_id

        # Even if another study has a persisted record, the adapter's
        # authenticated session lookup must prevent cross-study leakage.
        other_study_record = dict(persisted_records[0])
        other_study_record.update({
            "feature_record_id": f"feature-other-study-{request_id}",
            "study_id": f"other-study-{request_id}",
            "session_id": f"other-session-{request_id}",
        })
        telemetry_repository.persist_feature_record(other_study_record)
        assert [row["feature_record_id"] for row in feature_provider.get_for_analysis(
            study_id=study_id, feature_set_version="1.0.0",
        )] == [feature_record_id]

        p4_response = client.post("/v1/analytics/analyze", json={
            "schema_version": "1.0.0",
            "analysis_request_id": request_id,
            "study_id": study_id,
            "feature_set_version": "1.0.0",
            "modality_policy": "best_available",
            "analysis_types": ["descriptive"],
            "parameters": {"features": ["gaze.dwell_time_ms"]},
        })
        assert p4_response.status_code == 200, p4_response.text
        result = p4_response.json()
        schema = json_load_fixture("contracts/schemas/analysis-result.v1.schema.json")
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(result)
        assert result["results"]["descriptive"]["gaze.dwell_time_ms"]["mean"] == 200
        assert result["results"]["p4_provenance"]["feature_record_ids"] == [feature_record_id]
    finally:
        telemetry_repository.delete_session(session_id)
        telemetry_repository.delete_session(f"other-session-{request_id}")
        engine.dispose()


def test_p3_non_gaze_feature_record_preserves_missingness_through_p4(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise the real P3 processing/persistence path for camera denial."""
    database_url = os.environ.get(
        "TEST_DATABASE_URL",
        os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://attention:attention@localhost:5432/attention?connect_timeout=5",
        ),
    )
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
    except OperationalError as exc:
        engine.dispose()
        pytest.skip(f"PostgreSQL test database unavailable: {exc}")

    from services.feature_engine.authorized_gaze import AuthorizedGazeContext

    session_id = f"session-p3-p4-denied-{uuid4()}"
    study_id = f"study-p3-p4-denied-{uuid4()}"
    trial_id = f"trial-p3-p4-denied-{uuid4()}"
    request_id = f"request-p3-p4-denied-{uuid4()}"
    aoi_version = "aoi-denied-v1"
    start_at, end_at = "2026-01-01T10:00:00Z", "2026-01-01T10:00:10Z"
    context = AuthorizedGazeContext(
        experience_id=f"experience-{request_id}",
        session_id=session_id,
        study_id=study_id,
        trial_id=trial_id,
        aoi_set_version=aoi_version,
        observation_context=TrialObservationContext(
            session_id, study_id, trial_id, aoi_version, start_at, end_at,
        ),
        geometry_snapshots=[],
        events=[],
        start_event=None,
        requested_aoi_id=None,
        gaze_available=False,
        gaze_missingness="gaze.permission_denied",
    )
    repository = TelemetryRepository(engine)
    analysis_repository = MemoryAnalysisRepository()
    provider = TelemetryFeatureRecordProvider(
        repository,
        session_ids_for_study=lambda requested_study: [session_id]
        if requested_study == study_id else [],
    )
    app = FastAPI()
    app.include_router(create_analytics_router(
        get_feature_provider=lambda: provider,
        get_repository=lambda: analysis_repository,
        get_study_authorizer=lambda: lambda requested_study: requested_study == study_id,
    ))
    try:
        p3_result = process_authorized_gaze([], context=context, repository=repository)
        assert p3_result.feature_record["modality"] == "non_gaze_only"
        assert "gaze.permission_denied" in p3_result.feature_record["quality"]["missingness"]

        response = TestClient(app).post("/v1/analytics/analyze", json={
            "schema_version": "1.0.0",
            "analysis_request_id": request_id,
            "study_id": study_id,
            "feature_set_version": "1.0.0",
            "modality_policy": "best_available",
            "analysis_types": ["descriptive"],
            "parameters": {"features": ["gaze.dwell_time_ms"]},
        })
        assert response.status_code == 200, response.text
        result = response.json()
        schema = json_load_fixture("contracts/schemas/analysis-result.v1.schema.json")
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(result)
        assert result["status"] == "insufficient_data"
        assert result["modality"] == "non_gaze_only"
        assert result["results"]["p4_provenance"]["quality"]["gaze_unavailable_record_n"] == 1
        assert "gaze.permission_denied" in result["results"]["p4_provenance"]["quality"]["missingness_reason_codes"]
        summary = result["results"]["descriptive"]["gaze.dwell_time_ms"]
        assert summary["n"] == 0 and summary["missing_n"] == 1
    finally:
        repository.delete_session(session_id)
        engine.dispose()


def json_load_fixture(relative_path: str) -> dict:
    from json import loads
    from pathlib import Path

    repository_root = Path(__file__).resolve().parents[1]
    return loads((repository_root / relative_path).read_text(encoding="utf-8"))
