from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from services.feature_engine.gaze_pipeline import process_trial_gaze
from services.gaze_engine.adapter import GazeNormalizationError
from services.gaze_engine.context import TrialObservationContext

SESSION_ID = "session-pipeline-1"
STUDY_ID = "study-pipeline-a"
TRIAL_ID = "trial-pipeline-1"
AOI_VERSION = "aoi-pipeline-v1"
START = "2026-01-01T10:00:00Z"
END = "2026-01-01T10:00:10Z"


def context() -> TrialObservationContext:
    return TrialObservationContext(SESSION_ID, STUDY_ID, TRIAL_ID, AOI_VERSION, START, END)


def provider_sample(sample_id: str, offset_ms: int, *, x: float = 25, y: float = 25) -> dict:
    occurred = datetime(2026, 1, 1, 10, 0, tzinfo=UTC) + timedelta(milliseconds=offset_ms)
    return {
        "schema_version": "1.0.0",
        "provider": "synthetic-provider",
        "provider_version": "fixture-1",
        "sample_id": sample_id,
        "capture_time_ms": offset_ms,
        "occurred_at": occurred.isoformat().replace("+00:00", "Z"),
        "x_px": x,
        "y_px": y,
        "valid": True,
        "quality": {"confidence": 0.9, "flags": []},
    }


def start_event() -> dict:
    return {
        "schema_version": "1.0.0",
        "event_id": "start-pipeline-1",
        "experience_id": "experience-pipeline",
        "study_ids": [STUDY_ID],
        "session_id": SESSION_ID,
        "event_type": "trial.exposure_started",
        "occurred_at": START,
        "payload": {"trial_id": TRIAL_ID},
    }


def geometry() -> dict:
    return {
        "schema_version": "2.0.0",
        "snapshot_id": "geometry-pipeline-1",
        "session_id": SESSION_ID,
        "study_id": STUDY_ID,
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


def events() -> list[dict]:
    return [{
        "event_type": "interaction.click",
        "payload": {"scroll_delta_px": 0},
    }]


def run(samples: list[dict], *, gaze_available: bool = True, missingness: str | None = None) -> dict:
    return process_trial_gaze(
        samples,
        experience_id="experience-pipeline",
        session_id=SESSION_ID,
        study_id=STUDY_ID,
        trial_id=TRIAL_ID,
        aoi_set_version=AOI_VERSION,
        observation_context=context(),
        geometry_snapshots=[geometry()],
        events=events(),
        start_event=start_event() if gaze_available else None,
        requested_aoi_id="target",
        viewport_width_px=100,
        viewport_height_px=100,
        gaze_available=gaze_available,
        gaze_missingness=missingness,
    )


def assert_feature_record_schema(record: dict) -> None:
    schema = json.loads(Path("contracts/schemas/feature-record.v1.schema.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(record)


def test_end_to_end_gaze_path_is_schema_valid_and_reproducible():
    samples = [provider_sample("s2", 200), provider_sample("s0", 0), provider_sample("s1", 100)]
    first = run(samples)
    second = run(list(reversed(samples)))
    assert first == second
    assert_feature_record_schema(first)
    assert first["session_id"] == SESSION_ID
    assert first["study_id"] == STUDY_ID
    assert first["modality"] == "gaze_and_non_gaze"
    assert first["features"]["gaze.ttff_ms"]["value"] == 0
    assert first["features"]["gaze.dwell_time_ms"]["value"] == 200
    assert first["features"]["gaze.dwell_time_ms"]["window_end"] == END


def test_camera_denied_produces_non_gaze_record_without_fabricated_metrics():
    record = run([], gaze_available=False, missingness="gaze.permission_denied")
    assert_feature_record_schema(record)
    assert record["modality"] == "non_gaze_only"
    assert record["features"]["gaze.ttff_ms"]["value"] is None
    assert record["features"]["gaze.dwell_time_ms"]["value"] is None
    assert "gaze.permission_denied" in record["quality"]["missingness"]
    assert record["features"]["interaction.click_count"] == 1


def test_empty_capture_is_missing_not_a_measured_zero():
    record = run([])
    assert_feature_record_schema(record)
    assert record["features"]["gaze.dwell_time_ms"]["value"] is None
    assert record["features"]["gaze.dwell_time_ms"]["missingness"] == "gaze.no_samples"
    assert record["features"]["interaction.click_count"] == 1


def test_pipeline_rejects_context_mismatch_and_end_boundary_sample():
    with pytest.raises(ValueError, match="does not match"):
        process_trial_gaze(
            [], experience_id="experience-pipeline", session_id=SESSION_ID,
            study_id="study-other", trial_id=TRIAL_ID, aoi_set_version=AOI_VERSION,
            observation_context=context(), geometry_snapshots=[geometry()], events=events(),
            start_event=None, requested_aoi_id="target",
        )
    with pytest.raises(GazeNormalizationError, match="outside the observation window"):
        run([provider_sample("at-end", 10_000)])


def test_pipeline_does_not_use_geometry_from_another_study():
    wrong_study_geometry = {**geometry(), "study_id": "study-other"}
    record = process_trial_gaze(
        [provider_sample("s0", 0), provider_sample("s1", 100), provider_sample("s2", 200)],
        experience_id="experience-pipeline", session_id=SESSION_ID, study_id=STUDY_ID,
        trial_id=TRIAL_ID, aoi_set_version=AOI_VERSION, observation_context=context(),
        geometry_snapshots=[wrong_study_geometry], events=events(), start_event=start_event(),
        requested_aoi_id="target", viewport_width_px=100, viewport_height_px=100,
    )
    assert record["features"]["gaze.ttff_ms"]["value"] is None
    assert record["features"]["gaze.ttff_ms"]["missingness"] == "gaze.no_qualifying_fixation"
