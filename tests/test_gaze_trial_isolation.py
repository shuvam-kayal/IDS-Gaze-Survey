from __future__ import annotations

import pytest

from services.feature_engine.gaze_metrics import compute_gaze_metrics
from services.gaze_engine.adapter import GazeNormalizationError
from services.gaze_engine.context import TrialObservationContext, validate_observation_association
from services.gaze_engine.fixation import AOIAssignment, Fixation, map_gaze_to_aois
from services.gaze_engine.lifecycle import END_EVENT_TYPE, START_EVENT_TYPE, resolve_trial_lifecycle


def _event(event_type: str, event_id: str, occurred_at: str, trial_id: str = "trial-a") -> dict:
    return {
        "schema_version": "1.0.0",
        "event_id": event_id,
        "experience_id": "exp-1",
        "study_ids": ["study-a"],
        "session_id": "session-1",
        "event_type": event_type,
        "occurred_at": occurred_at,
        "payload": {"trial_id": trial_id},
    }


def _context(trial_id: str = "trial-a") -> TrialObservationContext:
    return TrialObservationContext(
        "session-1", "study-a", trial_id, "aoi-a",
        "2026-01-01T10:00:00Z", "2026-01-01T10:00:10Z",
    )


def _fixation(fixation_id: str, start: str, context: TrialObservationContext) -> Fixation:
    return Fixation(fixation_id, (fixation_id + "-sample",), start, "2026-01-01T10:00:02Z", 100, .2, .2,
                    session_id=context.session_id, study_id=context.study_id, trial_id=context.trial_id,
                    aoi_set_version=context.aoi_set_version)


def test_lifecycle_is_study_scoped_and_exact_retries_are_idempotent():
    context, reason = resolve_trial_lifecycle(
        [_event(START_EVENT_TYPE, "start-1", "2026-01-01T10:00:00Z")] * 2,
        [_event(END_EVENT_TYPE, "end-1", "2026-01-01T10:00:10Z")],
        session_id="session-1", study_id="study-a", aoi_set_version="aoi-a",
    )
    assert reason is None
    assert context == _context()


def test_missing_end_and_end_before_start_are_not_complete_windows():
    context, reason = resolve_trial_lifecycle(
        [_event(START_EVENT_TYPE, "start-1", "2026-01-01T10:00:00Z")], [],
        session_id="session-1", study_id="study-a", aoi_set_version="aoi-a",
    )
    assert context is None and reason == "gaze.observation_end_missing"
    context, reason = resolve_trial_lifecycle(
        [_event(START_EVENT_TYPE, "start-1", "2026-01-01T10:00:10Z")],
        [_event(END_EVENT_TYPE, "end-1", "2026-01-01T10:00:09Z")],
        session_id="session-1", study_id="study-a", aoi_set_version="aoi-a",
    )
    assert context is None and reason == "gaze.observation_boundary_invalid"


def test_association_rejects_samples_outside_the_explicit_trial_window():
    association = {
        "schema_version": "1.0.0", "association_id": "assoc-1", "session_id": "session-1",
        "study_id": "study-a", "trial_id": "trial-a", "aoi_set_version": "aoi-a",
        "window_start": "2026-01-01T10:00:00Z", "window_end": "2026-01-01T10:00:10Z",
        "gaze_records": [{
            "schema_version": "1.0.0", "sample_id": "sample-1", "session_id": "session-1",
            "occurred_at": "2026-01-01T10:00:11Z", "coordinate_space": "viewport_normalized",
            "x_normalized": .2, "y_normalized": .2, "confidence": .9, "valid": True,
            "calibration_status": "passed", "quality_flags": [],
        }],
    }
    with pytest.raises(GazeNormalizationError, match="outside the observation window"):
        validate_observation_association(association)


def test_empty_window_is_missing_not_a_measured_zero_and_context_is_checked():
    context = _context()
    metrics = compute_gaze_metrics([], [], session_id="session-1", study_id="study-a", aoi_set_version="aoi-a",
                                   requested_aoi_id="target", start_event=None, observation_context=context)
    assert all(metric["value"] is None for metric in metrics.values())
    assert all(metric["missingness"] == "gaze.no_qualifying_observations" for metric in metrics.values())
    wrong = _fixation("f-1", "2026-01-01T10:00:01Z", _context("other-trial"))
    with pytest.raises(GazeNormalizationError, match="context does not match"):
        compute_gaze_metrics([wrong], [AOIAssignment("f-1", "target", "geometry-1", None)],
                             session_id="session-1", study_id="study-a", aoi_set_version="aoi-a",
                             requested_aoi_id="target", start_event=None, observation_context=context)


def test_contextualized_fixations_cannot_be_processed_without_trial_context():
    fixation = _fixation("f-1", "2026-01-01T10:00:01Z", _context())
    with pytest.raises(GazeNormalizationError, match="observation_context is required"):
        compute_gaze_metrics([fixation], [AOIAssignment("f-1", "target", "geometry-1", None)],
                             session_id="session-1", study_id="study-a", aoi_set_version="aoi-a",
                             requested_aoi_id="target", start_event=None)


def test_v2_mapping_rejects_ambiguous_context():
    snapshot = {
        "schema_version": "2.0.0", "snapshot_id": "geometry-1", "session_id": "session-1",
        "study_id": "study-a", "captured_at": "2026-01-01T09:59:00Z", "aoi_set_version": "aoi-a",
        "viewport_width_px": 100, "viewport_height_px": 100, "scroll_x_px": 0, "scroll_y_px": 0,
        "zoom": 1, "rectangles": [],
    }
    with pytest.raises(GazeNormalizationError, match="required"):
        map_gaze_to_aois([], [snapshot])
