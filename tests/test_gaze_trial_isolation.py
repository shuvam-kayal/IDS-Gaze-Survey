from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from services.feature_engine.gaze_metrics import compute_gaze_metrics
from services.gaze_engine.adapter import GazeNormalizationError
from services.gaze_engine.context import TrialObservationContext, validate_observation_association
from services.gaze_engine.fixation import AOIAssignment, Fixation, map_gaze_to_aois
from services.gaze_engine.lifecycle import (
    END_EVENT_TYPE,
    START_EVENT_TYPE,
    resolve_authorized_trial_lifecycle,
    resolve_trial_lifecycle,
)


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
    end = (datetime.fromisoformat(start) + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    return Fixation(fixation_id, (fixation_id + "-sample",), start, end, 100, .2, .2,
                    session_id=context.session_id, study_id=context.study_id, trial_id=context.trial_id,
                    aoi_set_version=context.aoi_set_version)


def _record(sample_id: str = "sample-1", *, occurred_at: str = "2026-01-01T10:00:01Z", session_id: str = "session-1") -> dict:
    return {
        "schema_version": "1.0.0", "sample_id": sample_id, "session_id": session_id,
        "occurred_at": occurred_at, "coordinate_space": "viewport_normalized",
        "x_normalized": .2, "y_normalized": .2, "confidence": .9, "valid": True,
        "calibration_status": "passed", "quality_flags": [],
    }


def _association(records: list[dict] | None = None) -> dict:
    return {
        "schema_version": "1.0.0", "association_id": "assoc-1", "session_id": "session-1",
        "study_id": "study-a", "trial_id": "trial-a", "aoi_set_version": "aoi-a",
        "window_start": "2026-01-01T10:00:00Z", "window_end": "2026-01-01T10:00:10Z",
        "gaze_records": [_record()] if records is None else records,
    }


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
    association = _association([_record(occurred_at="2026-01-01T10:00:11Z")])
    with pytest.raises(GazeNormalizationError, match="outside the observation window"):
        validate_observation_association(association)


def test_valid_association_accepts_a_canonical_record_and_rejects_nested_errors():
    context, records = validate_observation_association(_association())
    assert context.trial_id == "trial-a"
    assert records[0]["sample_id"] == "sample-1"
    invalid_records = [
        [{**_record(), "confidence": 2}],
        [_record(), _record()],
        [_record(session_id="session-other")],
    ]
    for records in invalid_records:
        with pytest.raises(GazeNormalizationError):
            validate_observation_association(_association(records))
    for invalid in (
        {**_association(), "study_id": ""},
        {**_association(), "window_start": "not-a-time"},
        {**_association(), "window_end": "2026-01-01T09:59:59Z"},
    ):
        with pytest.raises(GazeNormalizationError):
            validate_observation_association(invalid)


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


def test_window_filtering_does_not_turn_outside_fixations_into_zero():
    context = _context()
    outside = _fixation("outside", "2026-01-01T10:00:20Z", context)
    metrics = compute_gaze_metrics(
        [outside], [AOIAssignment("outside", "target", "geometry-1", None)],
        session_id="session-1", study_id="study-a", aoi_set_version="aoi-a",
        requested_aoi_id="target", start_event=None, observation_context=context,
    )
    assert metrics["gaze.dwell_time_ms"] == {
        **metrics["gaze.dwell_time_ms"], "value": None,
        "missingness": "gaze.no_qualifying_observations",
    }


def test_start_event_must_match_context_identity_and_window_start():
    context = _context()
    fixation = _fixation("f-1", "2026-01-01T10:00:01Z", context)
    assignment = AOIAssignment("f-1", "target", "geometry-1", None)
    with pytest.raises(GazeNormalizationError, match="window_start"):
        compute_gaze_metrics(
            [fixation], [assignment], session_id="session-1", study_id="study-a", aoi_set_version="aoi-a",
            requested_aoi_id="target", start_event=_event(START_EVENT_TYPE, "start-1", "2026-01-01T10:00:02Z"),
            observation_context=context,
        )
    with pytest.raises(GazeNormalizationError, match="trial_id"):
        compute_gaze_metrics(
            [fixation], [assignment], session_id="session-1", study_id="study-a", aoi_set_version="aoi-a",
            requested_aoi_id="target", start_event=_event(START_EVENT_TYPE, "start-1", "2026-01-01T10:00:00Z", "other-trial"),
            observation_context=context,
        )


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


class _EventRepository:
    def __init__(self, events):
        self.events = events

    def list_events(self, session_id, *, study_id=None):
        return [
            event for event in self.events
            if event["session_id"] == session_id
            and (study_id is None or study_id in event["study_ids"])
        ]


def _verified_session(*, status="open", expires_at="2026-01-01T11:00:00Z"):
    return {
        "session_id": "session-1",
        "experience_id": "exp-1",
        "status": status,
        "expires_at": expires_at,
    }


def _assignment(*, study_id="study-a", aoi_set_version="aoi-a"):
    return {
        "session_id": "session-1",
        "experience_id": "exp-1",
        "assignments": [{
            "study_id": study_id,
            "config_version": "cfg-a",
            "study_config": {"aoi_set_version": aoi_set_version},
        }],
    }


def test_authorized_lifecycle_uses_verified_assignment_and_persisted_events():
    repository = _EventRepository([
        _event(START_EVENT_TYPE, "start-1", "2026-01-01T10:00:00Z"),
        _event(END_EVENT_TYPE, "end-1", "2026-01-01T10:00:10Z"),
    ])
    context, reason = resolve_authorized_trial_lifecycle(
        repository,
        participant_session=_verified_session(),
        study_assignment=_assignment(),
        study_id="study-a",
        trial_id="trial-a",
        aoi_set_version="aoi-a",
        now=datetime(2026, 1, 1, 10, 30, tzinfo=UTC),
    )
    assert reason is None
    assert context == _context()


def test_authorized_lifecycle_rejects_untrusted_or_ambiguous_scope():
    repository = _EventRepository([
        _event(START_EVENT_TYPE, "start-1", "2026-01-01T10:00:00Z"),
        _event(END_EVENT_TYPE, "end-1", "2026-01-01T10:00:10Z"),
    ])
    with pytest.raises(GazeNormalizationError, match="not open"):
        resolve_authorized_trial_lifecycle(
            repository,
            participant_session=_verified_session(status="withdrawn"),
            study_assignment=_assignment(), study_id="study-a", trial_id="trial-a",
            aoi_set_version="aoi-a", now=datetime(2026, 1, 1, 10, 30, tzinfo=UTC),
        )
    with pytest.raises(GazeNormalizationError, match="pinned"):
        resolve_authorized_trial_lifecycle(
            repository,
            participant_session=_verified_session(), study_assignment=_assignment(),
            study_id="study-a", trial_id="trial-a", aoi_set_version="aoi-other",
            now=datetime(2026, 1, 1, 10, 30, tzinfo=UTC),
        )
    with pytest.raises(GazeNormalizationError, match="not unambiguously assigned"):
        resolve_authorized_trial_lifecycle(
            repository,
            participant_session=_verified_session(), study_assignment=_assignment(study_id="study-b"),
            study_id="study-a", trial_id="trial-a", aoi_set_version="aoi-a",
            now=datetime(2026, 1, 1, 10, 30, tzinfo=UTC),
        )


def test_authorized_lifecycle_rejects_expired_session_and_wrong_experience_event():
    repository = _EventRepository([
        _event(START_EVENT_TYPE, "start-1", "2026-01-01T10:00:00Z"),
        _event(END_EVENT_TYPE, "end-1", "2026-01-01T10:00:10Z"),
    ])
    with pytest.raises(GazeNormalizationError, match="expired"):
        resolve_authorized_trial_lifecycle(
            repository,
            participant_session=_verified_session(expires_at="2026-01-01T10:30:00Z"),
            study_assignment=_assignment(), study_id="study-a", trial_id="trial-a",
            aoi_set_version="aoi-a", now=datetime(2026, 1, 1, 10, 30, tzinfo=UTC),
        )
    wrong_experience = _event(START_EVENT_TYPE, "start-2", "2026-01-01T10:00:00Z")
    wrong_experience["experience_id"] = "exp-other"
    with pytest.raises(GazeNormalizationError, match="Experience"):
        resolve_trial_lifecycle(
            [wrong_experience],
            [_event(END_EVENT_TYPE, "end-1", "2026-01-01T10:00:10Z")],
            session_id="session-1", study_id="study-a", aoi_set_version="aoi-a",
            trial_id="trial-a", experience_id="exp-1",
        )


def test_late_event_does_not_rewrite_or_extend_a_closed_window():
    starts = [_event(START_EVENT_TYPE, "start-1", "2026-01-01T10:00:00Z")]
    ends = [_event(END_EVENT_TYPE, "end-1", "2026-01-01T10:00:10Z")]
    context, reason = resolve_trial_lifecycle(
        starts, ends, session_id="session-1", study_id="study-a", aoi_set_version="aoi-a", trial_id="trial-a"
    )
    assert reason is None and context == _context()
    late_end = _event(END_EVENT_TYPE, "end-late", "2026-01-01T10:00:20Z")
    context, reason = resolve_trial_lifecycle(
        starts, ends + [late_end], session_id="session-1", study_id="study-a", aoi_set_version="aoi-a", trial_id="trial-a"
    )
    assert context is None and reason == "gaze.observation_boundary_ambiguous"
