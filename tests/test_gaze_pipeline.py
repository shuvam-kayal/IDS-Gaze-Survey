from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from services.feature_engine.gaze_pipeline import process_session_gaze, process_trial_gaze
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
    assert record["features"]["gaze.ttff_ms"]["missingness"] == "gaze.geometry_unavailable"


def _multi_context(study_id: str, trial_id: str, version: str, start: str, end: str) -> TrialObservationContext:
    return TrialObservationContext(SESSION_ID, study_id, trial_id, version, start, end)


def _multi_geometry(study_id: str, version: str, aoi_id: str, left: int, right: int) -> dict:
    value = geometry()
    value.update({"snapshot_id": f"geometry-{study_id}", "study_id": study_id, "aoi_set_version": version})
    value["rectangles"] = [{"aoi_id": aoi_id, "left_px": left, "top_px": 0, "right_px": right, "bottom_px": 50, "priority": 1}]
    return value


def _scoped_event(study_id: str, event_id: str) -> dict:
    value = start_event()
    value.update({"event_id": event_id, "study_ids": [study_id], "event_type": "interaction.click"})
    return value


def _bootstrap(studies: list[dict]) -> dict:
    return {
        "schema_version": "1.0.0", "session_id": SESSION_ID, "experience_id": "experience-pipeline",
        "experience_config_version": "experience-v1", "eligible_studies": studies,
        "privacy_notice_version": "privacy-v1", "research_consent_version": "consent-v1",
        "camera_capture_supported": True, "issued_at": "2026-01-01T09:00:00Z",
        "expires_at": "2026-01-01T11:00:00Z",
    }


def test_multi_study_session_isolates_versions_trials_and_partial_gaze():
    studies = [
        {"study_id": "study-a", "config_version": "config-a", "aoi_set_version": "aoi-a", "question_set_version": "questions-a"},
        {"study_id": "study-b", "config_version": "config-b", "aoi_set_version": "aoi-b", "question_set_version": "questions-b"},
    ]
    trials = [
        {
            "study_id": "study-a", "trial_id": "trial-a", "observation_context": _multi_context("study-a", "trial-a", "aoi-a", START, "2026-01-01T10:00:05Z"),
            "provider_samples": [], "geometry_snapshots": [_multi_geometry("study-a", "aoi-a", "aoi-a-target", 0, 50)],
            "start_event": None, "requested_aoi_id": "aoi-a-target", "gaze_available": False,
            "gaze_missingness": "gaze.permission_denied",
        },
        {
            "study_id": "study-b", "trial_id": "trial-b", "observation_context": _multi_context("study-b", "trial-b", "aoi-b", "2026-01-01T10:00:05Z", END),
            "provider_samples": [provider_sample("b2", 5200, x=75), provider_sample("b0", 5000, x=75), provider_sample("b1", 5100, x=75)],
            "geometry_snapshots": [_multi_geometry("study-b", "aoi-b", "aoi-b-target", 50, 100)],
            "start_event": {**start_event(), "event_id": "start-b", "study_ids": ["study-b"], "occurred_at": "2026-01-01T10:00:05Z", "payload": {"trial_id": "trial-b"}},
            "requested_aoi_id": "aoi-b-target", "viewport_width_px": 100, "viewport_height_px": 100,
        },
    ]
    all_events = [_scoped_event("study-a", "click-a"), _scoped_event("study-b", "click-b")]
    first = process_session_gaze(trials, session_bootstrap=_bootstrap(studies), experience_id="experience-pipeline", session_id=SESSION_ID, events=all_events)
    second = process_session_gaze(list(reversed(trials)), session_bootstrap=_bootstrap(studies), experience_id="experience-pipeline", session_id=SESSION_ID, events=list(reversed(all_events)))
    assert first == second
    assert [record["study_id"] for record in first] == ["study-a", "study-b"]
    assert first[0]["modality"] == "non_gaze_only"
    assert first[0]["features"]["interaction.click_count"] == 1
    assert first[1]["features"]["interaction.click_count"] == 1
    assert first[1]["features"]["gaze.dwell_time_ms"]["value"] == 200


def test_multi_study_requires_pinned_versions_and_does_not_fallback_geometry():
    studies = [{"study_id": "study-a", "config_version": "config-a", "aoi_set_version": "aoi-a", "question_set_version": "questions-a"}]
    trial = {
        "study_id": "study-a", "trial_id": "trial-a", "aoi_set_version": "aoi-other",
        "observation_context": _multi_context("study-a", "trial-a", "aoi-a", START, END),
        "provider_samples": [], "geometry_snapshots": [], "start_event": None,
        "requested_aoi_id": "target", "gaze_available": False,
    }
    with pytest.raises(ValueError, match="AOI-set version"):
        process_session_gaze([trial], session_bootstrap=_bootstrap(studies), experience_id="experience-pipeline", session_id=SESSION_ID, events=[])


def test_missing_pinned_geometry_is_explicitly_unavailable():
    record = process_trial_gaze(
        [provider_sample("s0", 0), provider_sample("s1", 100), provider_sample("s2", 200)],
        experience_id="experience-pipeline", session_id=SESSION_ID, study_id=STUDY_ID,
        trial_id=TRIAL_ID, aoi_set_version=AOI_VERSION, observation_context=context(),
        geometry_snapshots=[], events=events(), start_event=start_event(), requested_aoi_id="target",
        viewport_width_px=100, viewport_height_px=100,
    )
    assert record["features"]["gaze.dwell_time_ms"]["value"] is None
    assert record["features"]["gaze.dwell_time_ms"]["missingness"] == "gaze.geometry_unavailable"
