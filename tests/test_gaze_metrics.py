from __future__ import annotations

import json

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from services.feature_engine.gaze_metrics import (
    build_gaze_feature_record,
    compute_gaze_metrics,
)
from services.gaze_engine.adapter import GazeNormalizationError
from services.gaze_engine.fixation import AOIAssignment, Fixation

SESSION_ID = "session-metrics-0001"
STUDY_ID = "study-a"
AOI_VERSION = "aoi-a"


def fixation(fixation_id: str, start_ms: int, aoi_id: str) -> Fixation:
    start_seconds = start_ms // 1000
    millis = start_ms % 1000
    start = f"2026-01-01T10:00:{start_seconds:02d}.{millis:03d}Z"
    end_ms = start_ms + 100
    end_seconds = end_ms // 1000
    end_millis = end_ms % 1000
    end = f"2026-01-01T10:00:{end_seconds:02d}.{end_millis:03d}Z"
    return Fixation(fixation_id, (f"{fixation_id}-sample",), start, end, 100, 0.2, 0.2)


def event_assignment(fixation_id: str, aoi_id: str) -> AOIAssignment:
    return AOIAssignment(fixation_id, aoi_id, "geometry-a", None)


def start_event(study_id: str = STUDY_ID) -> dict:
    return {
        "schema_version": "1.0.0",
        "event_id": "start-1",
        "experience_id": "experience-a",
        "study_ids": [study_id],
        "session_id": SESSION_ID,
        "event_type": "trial.exposure_started",
        "occurred_at": "2026-01-01T10:00:00Z",
        "payload": {"trial_id": "trial-a-1"},
    }


def test_metrics_are_deterministic_and_follow_frozen_definitions():
    fixations = [
        fixation("f0", 1000, "aoi-a"),
        fixation("f1", 1200, "aoi-a"),
        fixation("f2", 1400, "aoi-b"),
        fixation("f3", 1600, "aoi.unresolved"),
        fixation("f4", 1800, "aoi-a"),
    ]
    assignments = [event_assignment(f.fixation_id, aoi) for f, aoi in zip(fixations, ["aoi-a", "aoi-a", "aoi-b", "aoi.unresolved", "aoi-a"])]
    first = compute_gaze_metrics(
        fixations,
        assignments,
        session_id=SESSION_ID,
        study_id=STUDY_ID,
        aoi_set_version=AOI_VERSION,
        requested_aoi_id="aoi-a",
        start_event=start_event(),
    )
    second = compute_gaze_metrics(
        list(reversed(fixations)),
        list(reversed(assignments)),
        session_id=SESSION_ID,
        study_id=STUDY_ID,
        aoi_set_version=AOI_VERSION,
        requested_aoi_id="aoi-a",
        start_event=start_event(),
    )
    assert first == second
    assert first["gaze.ttff_ms"]["value"] == 1000
    assert first["gaze.dwell_time_ms"]["value"] == 300
    assert first["gaze.revisit_count"]["value"] == 1
    assert first["gaze.transition_count"]["value"] == 2
    assert first["gaze.transitions"]["value"] == [
        {"from_aoi_id": "aoi-a", "to_aoi_id": "aoi-b"},
        {"from_aoi_id": "aoi-b", "to_aoi_id": "aoi-a"},
    ]
    assert first["gaze.scan_path"]["value"] == ["aoi-a", "aoi-b", "aoi.unresolved", "aoi-a"]
    assert first["gaze.entropy_bits"]["value"] == pytest.approx(0.811278)


def test_zero_is_distinct_from_unavailable_and_single_category_entropy_is_zero():
    fixations = [fixation("f0", 100, "aoi-a"), fixation("f1", 300, "aoi-a")]
    assignments = [event_assignment("f0", "aoi-a"), event_assignment("f1", "aoi-a")]
    metrics = compute_gaze_metrics(
        fixations,
        assignments,
        session_id=SESSION_ID,
        study_id=STUDY_ID,
        aoi_set_version=AOI_VERSION,
        requested_aoi_id="aoi-missing",
        start_event=start_event(),
    )
    assert metrics["gaze.dwell_time_ms"]["value"] == 0
    assert metrics["gaze.dwell_time_ms"]["missingness"] is None
    assert metrics["gaze.ttff_ms"]["value"] is None
    assert metrics["gaze.ttff_ms"]["missingness"] == "gaze.no_qualifying_fixation"
    assert compute_gaze_metrics(
        fixations,
        assignments,
        session_id=SESSION_ID,
        study_id=STUDY_ID,
        aoi_set_version=AOI_VERSION,
        requested_aoi_id="aoi-a",
        start_event=start_event(),
    )["gaze.entropy_bits"]["value"] == 0


def test_missing_start_and_empty_or_unavailable_gaze_are_explicit():
    fixation_value = fixation("f0", 100, "aoi-a")
    assignment = event_assignment("f0", "aoi-a")
    missing_start = compute_gaze_metrics(
        [fixation_value],
        [assignment],
        session_id=SESSION_ID,
        study_id=STUDY_ID,
        aoi_set_version=AOI_VERSION,
        requested_aoi_id="aoi-a",
        start_event=None,
    )
    assert missing_start["gaze.ttff_ms"]["missingness"] == "gaze.observation_start_missing"
    empty = compute_gaze_metrics(
        [],
        [],
        session_id=SESSION_ID,
        study_id=STUDY_ID,
        aoi_set_version=AOI_VERSION,
        requested_aoi_id="aoi-a",
        start_event=None,
    )
    assert empty["gaze.dwell_time_ms"]["missingness"] == "gaze.no_samples"
    unavailable = compute_gaze_metrics(
        [],
        [],
        session_id=SESSION_ID,
        study_id=STUDY_ID,
        aoi_set_version=AOI_VERSION,
        requested_aoi_id="aoi-a",
        start_event=None,
        gaze_available=False,
        gaze_missingness="gaze.permission_denied",
    )
    assert all(metric["value"] is None for metric in unavailable.values())
    assert all(metric["missingness"] == "gaze.permission_denied" for metric in unavailable.values())


def test_start_event_context_and_assignment_identity_are_validated():
    with pytest.raises(GazeNormalizationError, match="study/session context"):
        compute_gaze_metrics(
            [],
            [],
            session_id=SESSION_ID,
            study_id=STUDY_ID,
            aoi_set_version=AOI_VERSION,
            requested_aoi_id="aoi-a",
            start_event=start_event("study-other"),
        )
    with pytest.raises(GazeNormalizationError, match="must match"):
        compute_gaze_metrics(
            [fixation("f0", 100, "aoi-a")],
            [],
            session_id=SESSION_ID,
            study_id=STUDY_ID,
            aoi_set_version=AOI_VERSION,
            requested_aoi_id="aoi-a",
            start_event=start_event(),
        )


def test_start_event_retries_are_idempotent_and_distinct_starts_are_ambiguous():
    fixation_value = fixation("f0", 100, "aoi-a")
    assignment = event_assignment("f0", "aoi-a")
    retry_metrics = compute_gaze_metrics(
        [fixation_value],
        [assignment],
        session_id=SESSION_ID,
        study_id=STUDY_ID,
        aoi_set_version=AOI_VERSION,
        requested_aoi_id="aoi-a",
        start_event=[start_event(), start_event()],
    )
    assert retry_metrics["gaze.ttff_ms"]["value"] == 100
    second_start = {**start_event(), "event_id": "start-2", "occurred_at": "2026-01-01T10:00:00.050Z"}
    ambiguous = compute_gaze_metrics(
        [fixation_value],
        [assignment],
        session_id=SESSION_ID,
        study_id=STUDY_ID,
        aoi_set_version=AOI_VERSION,
        requested_aoi_id="aoi-a",
        start_event=[start_event(), second_start],
    )
    assert ambiguous["gaze.ttff_ms"]["value"] is None
    assert ambiguous["gaze.ttff_ms"]["missingness"] == "gaze.observation_start_ambiguous"
    conflicting = {**start_event(), "payload": {"trial_id": "other-trial"}}
    with pytest.raises(GazeNormalizationError, match="conflicting duplicate"):
        compute_gaze_metrics(
            [fixation_value],
            [assignment],
            session_id=SESSION_ID,
            study_id=STUDY_ID,
            aoi_set_version=AOI_VERSION,
            requested_aoi_id="aoi-a",
            start_event=[start_event(), conflicting],
        )
def test_gaze_feature_record_is_schema_valid_and_preserves_non_gaze_fallback():
    metrics = compute_gaze_metrics(
        [],
        [],
        session_id=SESSION_ID,
        study_id=STUDY_ID,
        aoi_set_version=AOI_VERSION,
        requested_aoi_id="aoi-a",
        start_event=None,
        gaze_available=False,
        gaze_missingness="gaze.permission_denied",
    )
    event = {
        "event_type": "interaction.click",
        "payload": {},
    }
    record = build_gaze_feature_record(
        [event],
        metrics,
        experience_id="experience-a",
        study_id=STUDY_ID,
        session_id=SESSION_ID,
        aoi_set_version=AOI_VERSION,
        gaze_available=False,
        gaze_missingness_reason="gaze.permission_denied",
    )
    schema = json.loads((__import__("pathlib").Path("contracts/schemas/feature-record.v1.schema.json")).read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(record)
    assert record["modality"] == "non_gaze_only"
    assert record["quality"]["gaze_available"] is False
    assert record["features"]["gaze.ttff_ms"]["value"] is None
