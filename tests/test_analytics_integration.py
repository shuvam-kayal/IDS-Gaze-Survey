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

from services.analytics.engine import AnalysisError
from services.analytics.feature_records import adapt_records, to_engine_record
from services.analytics.integration import create_analytics_router
from services.analytics.persistence import AnalysisRepository, AnalysisRow
from services.feature_engine.gaze_pipeline import process_trial_gaze
from services.gaze_engine.context import TrialObservationContext

ROOT = Path(__file__).resolve().parents[1]
STUDY_ID = "study-product-evaluation"
FEATURE_SET_VERSION = "1.0.0"


def _load_json(path: str) -> Any:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def p3_gaze_feature_record() -> dict[str, Any]:
    sample = _load_json("fixtures/gaze/provider-sample-valid.json")
    sample["occurred_at"] = "2026-01-01T10:00:01Z"
    sample["capture_time_ms"] = 1000
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
        [sample], experience_id="exp-p4-fixture", session_id="session-p4-p3-fixture",
        study_id=STUDY_ID, trial_id="trial-p4-fixture", aoi_set_version="aoi-v1",
        observation_context=context, geometry_snapshots=[geometry], events=[event],
        start_event=start, requested_aoi_id="hero", viewport_width_px=1024,
        viewport_height_px=768,
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
    assert "quality" not in adapted["features"]["gaze.dwell_time_ms"]
    assert adapted["modality"] == ["gaze", "interaction"]


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
