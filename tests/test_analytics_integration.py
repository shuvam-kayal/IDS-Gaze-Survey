from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from services.analytics.engine import AnalysisError, analyze
from services.analytics.feature_records import (
    TelemetryFeatureRecordProvider,
    adapt_records,
    to_engine_record,
)
from services.analytics.integration import _frozen_result, create_analytics_router
from services.analytics.persistence import AnalysisRepository, AnalysisRow
from services.feature_engine.gaze_pipeline import process_trial_gaze
from services.gaze_engine.context import TrialObservationContext

ROOT = Path(__file__).resolve().parents[1]
STUDY_ID = "study-product-evaluation"
FEATURE_SET_VERSION = "1.0.0"


def _load_json(path: str) -> Any:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def p3_gaze_feature_record(*, gaze_available: bool = True) -> dict[str, Any]:
    sample = _load_json("fixtures/gaze/provider-sample-valid.json")
    samples = [
        {
            **sample,
            "sample_id": f"p4-p3-gaze-{offset}",
            "occurred_at": f"2026-01-01T10:00:0{offset // 1000}.{offset % 1000:03d}Z",
            "capture_time_ms": offset,
        }
        for offset in (1000, 1100, 1200)
    ]
    event = {
        "schema_version": "1.0.0", "event_id": "evt-p4-p3-fixture",
        "experience_id": "exp-p4-fixture", "study_ids": [STUDY_ID],
        "session_id": "session-p4-p3-fixture", "event_type": "interaction.click",
        "occurred_at": "2026-01-01T10:00:01Z", "payload": {"target_aoi_id": "hero"},
    }
    start = {
        "schema_version": "1.0.0", "event_id": "start-p4-p3-fixture",
        "experience_id": "exp-p4-fixture", "study_ids": [STUDY_ID],
        "session_id": "session-p4-p3-fixture", "event_type": "trial.exposure_started",
        "occurred_at": "2026-01-01T10:00:00Z", "payload": {"trial_id": "trial-p4-fixture"},
    }
    geometry = {
        "schema_version": "2.0.0", "snapshot_id": "geometry-p4-fixture",
        "session_id": "session-p4-p3-fixture", "study_id": STUDY_ID,
        "captured_at": "2026-01-01T09:59:00Z", "aoi_set_version": "aoi-v1",
        "viewport_width_px": 1024, "viewport_height_px": 768,
        "scroll_x_px": 0, "scroll_y_px": 0, "zoom": 1,
        "rectangles": [{"aoi_id": "hero", "left_px": 0, "top_px": 0,
                        "right_px": 1024, "bottom_px": 768, "priority": 1}],
    }
    context = TrialObservationContext(
        "session-p4-p3-fixture", STUDY_ID, "trial-p4-fixture", "aoi-v1",
        "2026-01-01T10:00:00Z", "2026-01-01T10:00:10Z",
    )
    return process_trial_gaze(
        samples, experience_id="exp-p4-fixture", session_id="session-p4-p3-fixture",
        study_id=STUDY_ID, trial_id="trial-p4-fixture", aoi_set_version="aoi-v1",
        observation_context=context, geometry_snapshots=[geometry], events=[event],
        start_event=start, requested_aoi_id="hero", viewport_width_px=1024,
        viewport_height_px=768,
        gaze_available=gaze_available,
    )


class MemoryRepository:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.requests: dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any]]] = {}

    def get_by_request(self, request_id: str, study_id: str) -> dict[str, Any] | None:
        item = self.requests.get((request_id, study_id))
        return item[1] if item else None

    def save(self, request: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        self.rows[result["analysis_id"]] = result
        self.requests[(request["analysis_request_id"], request["study_id"])] = (request, result)
        return result

    def get(self, analysis_id: str) -> dict[str, Any] | None:
        return self.rows.get(analysis_id)

    def update(self, result: dict[str, Any]) -> dict[str, Any]:
        self.rows[result["analysis_id"]] = result
        return result

    def list_page(self, study_id: str, limit: int, cursor: str | None) -> dict[str, Any]:
        values = [row for row in self.rows.values() if row["study_id"] == study_id][:limit]
        return {"results": values, "next_cursor": None, "limit": limit}


def request(**overrides: Any) -> dict[str, Any]:
    value = {
        "schema_version": "1.0.0", "analysis_request_id": "p4-test-request",
        "study_id": STUDY_ID, "feature_set_version": FEATURE_SET_VERSION,
        "modality_policy": "best_available", "analysis_types": ["descriptive"], "parameters": {},
    }
    value.update(overrides)
    return value


def test_real_p3_non_gaze_fixture_adapts_identity_quality_and_modality() -> None:
    record = _load_json("fixtures/feature-record-non-gaze.json")
    adapted = to_engine_record(record, study_id=record["study_id"], feature_set_version=record["feature_set_version"])
    assert adapted["record_id"] == record["feature_record_id"]
    assert adapted["session_id"] == record["session_id"]
    assert adapted["modality"] == ["interaction"]
    assert adapted["missingness"] == record["quality"]["missingness"]
    assert adapted["features"]["survey.completion_ratio"] == record["features"]["survey.completion_ratio"] is None


def test_p3_gaze_feature_record_maps_aoi_and_does_not_invent_numeric_quality() -> None:
    record = p3_gaze_feature_record()
    schema = _load_json("contracts/schemas/feature-record.v1.schema.json")
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(record)
    adapted = to_engine_record(record, study_id=STUDY_ID, feature_set_version=FEATURE_SET_VERSION)
    assert adapted["record_id"] == record["feature_record_id"]
    assert adapted["features"]["gaze.dwell_time_ms"]["aoi_id"] == "hero"
    assert adapted["features"]["gaze.dwell_time_ms"]["value"] == 200
    assert "quality" not in adapted["features"]["gaze.dwell_time_ms"]
    assert adapted["modality"] == ["gaze", "interaction"]
    assert "gaze.no_samples" not in adapted["missingness"]


@pytest.mark.parametrize(
    ("gaze_available", "expected_modality", "expected_analysis_modality"),
    [
        (True, "gaze_and_non_gaze", "gaze_and_non_gaze"),
        (False, "non_gaze_only", "non_gaze_only"),
    ],
)
def test_real_p3_feature_record_through_engine_analyze_matches_frozen_result(
    gaze_available: bool,
    expected_modality: str,
    expected_analysis_modality: str,
) -> None:
    record = p3_gaze_feature_record(gaze_available=gaze_available)
    feature_schema = _load_json("contracts/schemas/feature-record.v1.schema.json")
    Draft202012Validator(feature_schema, format_checker=FormatChecker()).validate(record)

    request_payload = request(
        analysis_request_id=f"p4-engine-{gaze_available}",
        modality_policy="best_available",
        analysis_types=["descriptive"],
        parameters={
            "features": ["gaze.dwell_time_ms", "interaction.click_count"],
            "gaze_required": True,
        },
    )
    internal_request = {
        "request_id": request_payload["analysis_request_id"],
        "study_id": request_payload["study_id"],
        "feature_set_version": request_payload["feature_set_version"],
        "modality_policy": request_payload["modality_policy"],
        "analysis_types": request_payload["analysis_types"],
        "parameters": request_payload["parameters"],
        "feature_records": adapt_records(
            [record],
            study_id=request_payload["study_id"],
            feature_set_version=request_payload["feature_set_version"],
        ),
    }

    internal_result = analyze(internal_request)
    result = _frozen_result(request_payload, internal_result, [record])
    result_schema = _load_json("contracts/schemas/analysis-result.v1.schema.json")
    Draft202012Validator(result_schema, format_checker=FormatChecker()).validate(result)

    assert record["modality"] == expected_modality
    assert result["study_id"] == record["study_id"] == STUDY_ID
    assert result["feature_set_version"] == record["feature_set_version"] == FEATURE_SET_VERSION
    assert result["modality"] == expected_analysis_modality
    assert result["sample_size"] == 1
    assert result["status"] == "succeeded"
    assert result["results"]["p4_provenance"]["feature_record_ids"] == [record["feature_record_id"]]

    descriptive = result["results"]["descriptive"]
    if gaze_available:
        assert descriptive["gaze.dwell_time_ms"]["mean"] == 200
        assert "No gaze-only claim is supported" not in result["limitations"]
    else:
        gaze_summary = descriptive["gaze.dwell_time_ms"]
        assert gaze_summary["kind"] == "unavailable"
        assert gaze_summary["n"] == 0
        assert "mean" not in gaze_summary
        assert result["results"]["p4_provenance"]["quality"]["gaze_unavailable_record_n"] == 1
        assert "No gaze-only claim is supported; gaze-dependent results may be unavailable." in result["limitations"]


def test_p3_gaze_pipeline_to_p4_api_is_end_to_end_and_frozen_contract_valid() -> None:
    record = p3_gaze_feature_record()
    repository = MemoryRepository()

    class P3TelemetryRepository:
        def list_feature_records(
            self, session_id: str, *, study_id: str | None = None
        ) -> list[dict[str, Any]]:
            assert session_id == record["session_id"]
            assert study_id == record["study_id"]
            return [record]

    provider = TelemetryFeatureRecordProvider(
        P3TelemetryRepository(),
        session_ids_for_study=lambda study_id: [record["session_id"]]
        if study_id == record["study_id"]
        else [],
    )

    app = FastAPI()
    app.include_router(create_analytics_router(
        get_feature_provider=lambda: provider,
        get_repository=lambda: repository,
        get_study_authorizer=lambda: lambda study_id: study_id == record["study_id"],
    ))
    response = TestClient(app).post(
        "/v1/analytics/analyze",
        json=request(
            study_id=record["study_id"],
            analysis_types=["descriptive"],
            parameters={"features": ["gaze.dwell_time_ms", "interaction.click_count"]},
        ),
    )
    assert response.status_code == 200, response.text
    result = response.json()
    result_schema = _load_json("contracts/schemas/analysis-result.v1.schema.json")
    Draft202012Validator(result_schema, format_checker=FormatChecker()).validate(result)
    assert result["status"] == "succeeded"
    assert result["sample_size"] == 1
    assert result["modality"] == "gaze_and_non_gaze"
    assert result["results"]["descriptive"]["gaze.dwell_time_ms"]["mean"] == 200
    provenance = result["results"]["p4_provenance"]
    assert provenance["feature_record_ids"] == [record["feature_record_id"]]
    assert provenance["session_ids"] == [record["session_id"]]
    assert "gaze.metric_undefined" in provenance["quality"]["missingness_reason_codes"]


def test_p3_feature_provider_filters_version_and_reads_only_authorized_sessions() -> None:
    gaze_record = p3_gaze_feature_record()
    non_gaze_record = _load_json("fixtures/feature-record-non-gaze.json")
    feature_store = {
        gaze_record["session_id"]: [gaze_record, {**gaze_record, "feature_set_version": "0.9.0"}],
        non_gaze_record["session_id"]: [non_gaze_record],
    }
    calls: list[tuple[str, str]] = []

    class P3TelemetryRepository:
        def list_feature_records(
            self, session_id: str, *, study_id: str | None = None
        ) -> list[dict[str, Any]]:
            calls.append((session_id, str(study_id)))
            return feature_store.get(session_id, [])

    provider = TelemetryFeatureRecordProvider(
        P3TelemetryRepository(),
        session_ids_for_study=lambda study_id: [
            gaze_record["session_id"],
            non_gaze_record["session_id"],
            gaze_record["session_id"],
        ] if study_id == STUDY_ID else [],
    )
    records = provider.get_for_analysis(study_id=STUDY_ID, feature_set_version=FEATURE_SET_VERSION)
    assert [row["feature_record_id"] for row in records] == sorted(
        [gaze_record["feature_record_id"], non_gaze_record["feature_record_id"]]
    )
    assert calls == sorted({
        (gaze_record["session_id"], STUDY_ID),
        (non_gaze_record["session_id"], STUDY_ID),
    })


def test_p3_feature_provider_rejects_records_outside_authorized_session_scope() -> None:
    record = _load_json("fixtures/feature-record-non-gaze.json")

    class LeakyP3Repository:
        def list_feature_records(self, _session_id: str, *, study_id: str | None = None) -> list[dict[str, Any]]:
            return [record]

    provider = TelemetryFeatureRecordProvider(
        LeakyP3Repository(), session_ids_for_study=lambda _study_id: ["authorized-session-only"],
    )
    with pytest.raises(AnalysisError, match="outside the authorized study/session scope"):
        provider.get_for_analysis(study_id=record["study_id"], feature_set_version=FEATURE_SET_VERSION)


def test_p3_gaze_api_persists_record_then_p4_api_analyzes_that_record(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.api import app as p3_api
    from services.feature_engine.authorized_gaze import AuthorizedGazeContext

    session_id = "session-p3-to-p4-api-e2e"
    trial_id = "trial-p3-to-p4-api-e2e"
    study_id = STUDY_ID
    start_at = "2026-01-01T10:00:00Z"
    end_at = "2026-01-01T10:00:10Z"
    observation_context = TrialObservationContext(
        session_id, study_id, trial_id, "aoi-p3-to-p4", start_at, end_at,
    )
    event = {
        "schema_version": "1.0.0", "event_id": "evt-p3-to-p4-e2e",
        "experience_id": "exp-p3-to-p4-e2e", "study_ids": [study_id],
        "session_id": session_id, "event_type": "interaction.click",
        "occurred_at": "2026-01-01T10:00:01Z", "payload": {},
    }
    start_event = {
        **event, "event_id": "start-p3-to-p4-e2e",
        "event_type": "trial.exposure_started", "occurred_at": start_at,
        "payload": {"trial_id": trial_id},
    }
    geometry = {
        "schema_version": "2.0.0", "snapshot_id": "geometry-p3-to-p4-e2e",
        "session_id": session_id, "study_id": study_id,
        "captured_at": "2026-01-01T09:59:00Z", "aoi_set_version": "aoi-p3-to-p4",
        "viewport_width_px": 1024, "viewport_height_px": 768,
        "scroll_x_px": 0, "scroll_y_px": 0, "zoom": 1,
        "rectangles": [{"aoi_id": "hero", "left_px": 0, "top_px": 0,
                        "right_px": 1024, "bottom_px": 768, "priority": 1}],
    }
    trusted_context = AuthorizedGazeContext(
        experience_id="exp-p3-to-p4-e2e", session_id=session_id, study_id=study_id,
        trial_id=trial_id, aoi_set_version="aoi-p3-to-p4",
        observation_context=observation_context, geometry_snapshots=[geometry],
        events=[event], start_event=start_event, requested_aoi_id="hero",
        viewport_width_px=1024, viewport_height_px=768,
    )

    class TrustedContextProvider:
        def resolve(self, request_body: dict[str, Any]) -> AuthorizedGazeContext:
            assert request_body["session_id"] == session_id
            return trusted_context

    class P3TelemetryRepository:
        def __init__(self) -> None:
            self.records: dict[str, dict[str, Any]] = {}
            self.associations: set[tuple[str, str]] = set()

        def persist_gaze_association(self, association: dict[str, Any]) -> None:
            self.associations.add((association["association_id"], association["session_id"]))

        def persist_feature_record(self, record: dict[str, Any]) -> dict[str, Any]:
            self.records[record["feature_record_id"]] = record
            return record

        def gaze_association_exists(self, association_id: str, session_id: str) -> bool:
            return (association_id, session_id) in self.associations

        def feature_record_exists(self, feature_record_id: str) -> bool:
            return feature_record_id in self.records

        def list_feature_records(self, requested_session: str, *, study_id: str | None = None) -> list[dict[str, Any]]:
            return [
                record for record in self.records.values()
                if record["session_id"] == requested_session and record["study_id"] == study_id
            ]

    p3_repository = P3TelemetryRepository()
    monkeypatch.setattr(p3_api, "_repository", p3_repository)
    monkeypatch.setattr(p3_api, "_gaze_context_provider", TrustedContextProvider())
    p4_repository = MemoryRepository()
    p4_provider = TelemetryFeatureRecordProvider(
        p3_repository, session_ids_for_study=lambda requested_study: [session_id]
        if requested_study == study_id else [],
    )

    app = FastAPI()
    app.add_api_route(
        "/v1/gaze/observations", p3_api.ingest_gaze_observation, methods=["POST"],
    )
    app.include_router(create_analytics_router(
        get_feature_provider=lambda: p4_provider,
        get_repository=lambda: p4_repository,
        get_study_authorizer=lambda: lambda requested_study: requested_study == study_id,
    ))
    provider_sample = _load_json("fixtures/gaze/provider-sample-valid.json")
    provider_samples = [
        {
            **provider_sample,
            "sample_id": f"api-e2e-sample-{offset}",
            "capture_time_ms": offset,
            "occurred_at": f"2026-01-01T10:00:0{offset // 1000}.{offset % 1000:03d}Z",
        }
        for offset in (1000, 1100, 1200)
    ]
    client = TestClient(app)
    p3_response = client.post("/v1/gaze/observations", json={
        "schema_version": "1.0.0", "request_id": "p3-to-p4-api-e2e",
        "session_id": session_id, "provider_samples": provider_samples,
    })
    assert p3_response.status_code == 202, p3_response.text
    feature_record_id = p3_response.json()["feature_record_id"]
    assert feature_record_id in p3_repository.records

    p4_response = client.post("/v1/analytics/analyze", json=request(
        analysis_request_id="p3-to-p4-api-e2e", study_id=study_id,
        parameters={"features": ["gaze.dwell_time_ms"]},
    ))
    assert p4_response.status_code == 200, p4_response.text
    result = p4_response.json()
    Draft202012Validator(
        _load_json("contracts/schemas/analysis-result.v1.schema.json"),
        format_checker=FormatChecker(),
    ).validate(result)
    assert result["results"]["descriptive"]["gaze.dwell_time_ms"]["mean"] == 200
    assert result["results"]["p4_provenance"]["feature_record_ids"] == [feature_record_id]


def test_p3_heatmap_provider_is_separate_scoped_and_runs_through_api() -> None:
    record = p3_gaze_feature_record()
    repository = MemoryRepository()
    points = [{"x": 0.25, "y": 0.5}, {"x": 0.4, "y": 0.6}]

    class P3FeatureRecordStore:
        def get_for_analysis(self, *, study_id: str, feature_set_version: str) -> list[dict[str, Any]]:
            return [record]

    class AuthorizedHeatmapStore:
        def get_for_feature_records(self, *, study_id: str, feature_record_ids: list[str]) -> dict[str, Any]:
            assert study_id == record["study_id"]
            assert feature_record_ids == [record["feature_record_id"]]
            return {
                record["feature_record_id"]: {
                    "schema_version": "1.0.0",
                    "feature_record_id": record["feature_record_id"],
                    "study_id": record["study_id"],
                    "session_id": record["session_id"],
                    "geometry_snapshot_id": "geometry-p4-fixture",
                    "coordinate_system": "normalized_viewport",
                    "quality": 0.9,
                    "points": points,
                    "geometry_version": "aoi-v1",
                    "aoi_geometry": {"hero": {"x": 0, "y": 0, "width": 1, "height": 1}},
                }
            }

    app = FastAPI()
    app.include_router(create_analytics_router(
        get_feature_provider=lambda: P3FeatureRecordStore(),
        get_repository=lambda: repository,
        get_study_authorizer=lambda: lambda study_id: study_id == record["study_id"],
        get_heatmap_provider=lambda: AuthorizedHeatmapStore(),
    ))
    payload = request(
        study_id=record["study_id"],
        parameters={
            "heatmap_min_points": 2,
            "p4_extension": {"schema_version": "1.0.0", "analysis_types": ["heatmap"]},
        },
    )
    response = TestClient(app).post("/v1/analytics/analyze", json=payload)
    assert response.status_code == 200, response.text
    heatmap = response.json()["results"]["heatmap"]
    assert heatmap["status"] == "succeeded"
    assert heatmap["point_n"] == len(points)
    assert heatmap["quality_mean"] == 0.9
    assert heatmap["overlay_status"] == "available"
    # The canonical FeatureRecord remains unchanged and does not acquire spatial data.
    assert "spatial" not in record


def test_p3_gaze_record_respects_each_frozen_modality_policy() -> None:
    record = p3_gaze_feature_record()

    class P3FeatureRecordStore:
        def get_for_analysis(self, *, study_id: str, feature_set_version: str) -> list[dict[str, Any]]:
            return [record]

    for policy, expected_feature_names in (
        ("best_available", {"gaze.dwell_time_ms", "interaction.click_count"}),
        ("gaze_only", {"gaze.dwell_time_ms"}),
        ("non_gaze_only", {"interaction.click_count"}),
    ):
        repository = MemoryRepository()
        app = FastAPI()
        app.include_router(create_analytics_router(
            get_feature_provider=lambda: P3FeatureRecordStore(),
            get_repository=lambda repository=repository: repository,
            get_study_authorizer=lambda: lambda study_id: study_id == record["study_id"],
        ))
        response = TestClient(app).post(
            "/v1/analytics/analyze",
            json=request(
                study_id=record["study_id"],
                analysis_request_id=f"p4-policy-{policy}",
                modality_policy=policy,
                parameters={"features": ["gaze.dwell_time_ms", "interaction.click_count"]},
            ),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert set(body["results"]["descriptive"]) == expected_feature_names
        assert body["results"]["p4_provenance"]["modality_policy"] == policy


def test_p3_record_scope_and_study_authorization_fail_closed_before_analysis() -> None:
    record = _load_json("fixtures/feature-record-non-gaze.json")
    repository = MemoryRepository()
    provider_calls = 0

    class Provider:
        def get_for_analysis(self, *, study_id: str, feature_set_version: str) -> list[dict[str, Any]]:
            nonlocal provider_calls
            provider_calls += 1
            return [{**record, "study_id": "study-other"}]

    app = FastAPI()
    app.include_router(create_analytics_router(
        get_feature_provider=lambda: Provider(), get_repository=lambda: repository,
        get_study_authorizer=lambda: lambda _study_id: True,
    ))
    client = TestClient(app)
    wrong_scope = client.post("/v1/analytics/analyze", json=request(study_id=record["study_id"]))
    assert wrong_scope.status_code == 422
    assert wrong_scope.json()["detail"]["code"] == "feature_record_scope_mismatch"

    forbidden_app = FastAPI()
    forbidden_app.include_router(create_analytics_router(
        get_feature_provider=lambda: Provider(), get_repository=lambda: repository,
        get_study_authorizer=lambda: lambda _study_id: False,
    ))
    forbidden = TestClient(forbidden_app).post(
        "/v1/analytics/analyze", json=request(study_id=record["study_id"]),
    )
    assert forbidden.status_code == 403
    assert provider_calls == 1


def test_heatmap_geometry_version_cannot_drift_from_p3_aoi_version() -> None:
    record = p3_gaze_feature_record()
    heatmap = {
        "schema_version": "1.0.0",
        "study_id": record["study_id"],
        "feature_record_id": record["feature_record_id"],
        "session_id": record["session_id"],
        "geometry_snapshot_id": "geometry-p4-fixture",
        "coordinate_system": "normalized_viewport",
        "quality": 0.9,
        "points": [{"x": 0.2, "y": 0.3}],
        "geometry_version": "aoi-stale-version",
        "aoi_geometry": {"hero": {"x": 0, "y": 0, "width": 1, "height": 1}},
    }
    with pytest.raises(AnalysisError, match="AOI-set version"):
        to_engine_record(
            record, study_id=STUDY_ID, feature_set_version=FEATURE_SET_VERSION,
            heatmap_input=heatmap,
        )


def test_shared_api_shell_can_mount_p4_router_without_replacing_p3_health_route() -> None:
    from services.api.app import app as shared_app

    repository = MemoryRepository()

    class EmptyP3FeatureRecordStore:
        def get_for_analysis(self, *, study_id: str, feature_set_version: str) -> list[dict[str, Any]]:
            return []

    shared_app.include_router(create_analytics_router(
        get_feature_provider=lambda: EmptyP3FeatureRecordStore(),
        get_repository=lambda: repository,
        get_study_authorizer=lambda: lambda _study_id: True,
    ))
    client = TestClient(shared_app)
    assert client.get("/health").status_code == 200
    assert client.get("/v1/analytics/models").status_code == 200
    assert client.post("/v1/analytics/analyze", json=request()).status_code == 200


def test_canonical_feature_record_rejects_noncanonical_spatial_field() -> None:
    record = _load_json("fixtures/feature-record-non-gaze.json")
    record["spatial"] = {"points": []}
    with pytest.raises(AnalysisError, match="outside the frozen v1 schema"):
        adapt_records([record], study_id=record["study_id"], feature_set_version=record["feature_set_version"])


def test_separate_heatmap_input_is_scope_checked_and_not_read_from_feature_record() -> None:
    record = p3_gaze_feature_record()
    heatmap = {
        "schema_version": "1.0.0", "feature_record_id": record["feature_record_id"],
        "study_id": record["study_id"], "session_id": record["session_id"],
        "geometry_snapshot_id": "geometry-p4-fixture", "coordinate_system": "normalized_viewport",
        "quality": 0.9, "points": [{"x": 0.25, "y": 0.5}, {"x": 0.4, "y": 0.6}],
        "geometry_version": "aoi-v1", "aoi_geometry": {"hero": {"x": 0, "y": 0, "width": 1, "height": 1}},
    }
    adapted = adapt_records([record], study_id=STUDY_ID, feature_set_version=FEATURE_SET_VERSION,
                            heatmap_inputs={record["feature_record_id"]: heatmap})
    assert "spatial" not in record
    assert adapted[0]["spatial"]["points"] == heatmap["points"]
    heatmap["session_id"] = "other-session"
    with pytest.raises(AnalysisError, match="match the canonical study"):
        adapt_records([record], study_id=STUDY_ID, feature_set_version=FEATURE_SET_VERSION,
                      heatmap_inputs={record["feature_record_id"]: heatmap})


def test_router_adapts_to_frozen_request_result_and_uses_injected_boundaries() -> None:
    record = _load_json("fixtures/feature-record-non-gaze.json")
    repository = MemoryRepository()

    class Provider:
        def get_for_analysis(self, *, study_id: str, feature_set_version: str) -> list[dict[str, Any]]:
            assert (study_id, feature_set_version) == (record["study_id"], record["feature_set_version"])
            return [record]

    app = FastAPI()
    app.include_router(create_analytics_router(
        get_feature_provider=lambda: Provider(), get_repository=lambda: repository,
        get_study_authorizer=lambda: lambda study_id: study_id == record["study_id"],
    ))
    client = TestClient(app)
    response = client.post("/v1/analytics/analyze", json=request(study_id=record["study_id"]))
    assert response.status_code == 200, response.text
    result = response.json()
    result_schema = _load_json("contracts/schemas/analysis-result.v1.schema.json")
    Draft202012Validator(result_schema, format_checker=FormatChecker()).validate(result)
    request_schema = _load_json("contracts/schemas/analysis-request.v1.schema.json")
    Draft202012Validator(request_schema, format_checker=FormatChecker()).validate(request(study_id=record["study_id"]))
    assert result["modality"] == "non_gaze_only"
    assert result["results"]["p4_provenance"]["feature_record_ids"] == [record["feature_record_id"]]
    assert result["results"]["p4_provenance"]["quality"]["missingness_reason_codes"] == ["gaze.permission_denied"]
    assert client.get(f"/v1/analytics/results/{result['analysis_id']}").status_code == 200
    assert client.get(f"/v1/analytics/results/{result['analysis_id']}/csv").status_code == 200
    assert client.get("/v1/analytics/results", params={"study_id": record["study_id"]}).status_code == 200


def test_router_job_lifecycle_returns_frozen_queued_then_completed_results() -> None:
    record = _load_json("fixtures/feature-record-non-gaze.json")
    repository = MemoryRepository()

    class Provider:
        def get_for_analysis(self, *, study_id: str, feature_set_version: str) -> list[dict[str, Any]]:
            return [record]

    app = FastAPI()
    app.include_router(create_analytics_router(
        get_feature_provider=lambda: Provider(), get_repository=lambda: repository,
        get_study_authorizer=lambda: lambda study_id: study_id == record["study_id"],
    ))
    client = TestClient(app)
    response = client.post("/v1/analytics/jobs", json=request(study_id=record["study_id"]))
    assert response.status_code == 202
    queued = response.json()
    schema = _load_json("contracts/schemas/analysis-result.v1.schema.json")
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(queued)
    assert queued["status"] == "queued"
    completed = client.get(f"/v1/analytics/jobs/{queued['analysis_id']}").json()
    assert completed["status"] == "succeeded"
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(completed)


def test_frozen_request_rejects_extra_top_level_fields_and_extension_is_versioned() -> None:
    from services.analytics.integration import _validate_v1

    with pytest.raises(AnalysisError, match="unsupported fields"):
        _validate_v1(request(feature_records=[]))
    extension = {"schema_version": "1.0.0", "analysis_types": ["heatmap"]}
    _validate_v1(request(parameters={"p4_extension": extension}))
    with pytest.raises(AnalysisError, match="P4 Analysis Extension v1"):
        _validate_v1(request(parameters={"p4_extension": {"analysis_types": ["heatmap"]}}))


def test_postgres_persistence_refuses_sqlite_and_schema_uses_jsonb() -> None:
    with pytest.raises(RuntimeError, match="requires PostgreSQL"):
        AnalysisRepository("sqlite:///not-allowed.db")
    compiled = str(CreateTable(AnalysisRow.__table__).compile(dialect=postgresql.dialect()))
    assert AnalysisRow.__tablename__ == "p4_analysis_results"
    assert "p4_analysis_results" in compiled
    assert "JSONB" in compiled
    with pytest.raises(RuntimeError, match="requires PostgreSQL"):
        AnalysisRepository("postgresql://host/db")


def test_compare_checks_scope_and_csv_escapes_formula_cells() -> None:
    record = _load_json("fixtures/feature-record-non-gaze.json")
    repository = MemoryRepository()

    class Provider:
        def get_for_analysis(self, *, study_id: str, feature_set_version: str) -> list[dict[str, Any]]:
            return [record]

    app = FastAPI()
    app.include_router(create_analytics_router(
        get_feature_provider=lambda: Provider(), get_repository=lambda: repository,
        get_study_authorizer=lambda: lambda study_id: study_id == record["study_id"],
    ))
    client = TestClient(app)
    first = client.post("/v1/analytics/analyze", json=request(study_id=record["study_id"])).json()
    second_request = request(study_id=record["study_id"], analysis_request_id="p4-second-request")
    second = client.post("/v1/analytics/analyze", json=second_request).json()
    comparison = client.get("/v1/analytics/compare", params={"left_id": first["analysis_id"], "right_id": second["analysis_id"]})
    assert comparison.status_code == 200
    assert comparison.json()["status"] == "comparable"

    unsafe = {**first, "analysis_id": "unsafe-export", "results": {"descriptive": {"=1+1": {"kind": "numeric", "n": 1, "mean": 2, "median": 2, "unit": None}}}}
    repository.rows["unsafe-export"] = unsafe
    exported = client.get("/v1/analytics/results/unsafe-export/csv")
    assert exported.status_code == 200
    assert b"'=1+1" in exported.content
