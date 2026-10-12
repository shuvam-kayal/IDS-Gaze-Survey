import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from services.feature_engine.non_gaze import build_non_gaze_feature_record
from services.telemetry.ingestion import deduplicate_events, validate_event


ROOT = Path(__file__).resolve().parents[1]


def load_events() -> list[dict]:
    return json.loads((ROOT / "fixtures/events/non-gaze-session.json").read_text())


def feature_schema() -> dict:
    return json.loads((ROOT / "contracts/schemas/feature-record.v1.schema.json").read_text())


def test_normal_input_deduplicates_and_builds_schema_valid_record():
    events = load_events()
    record = build_non_gaze_feature_record(
        events + [events[0]],
        survey_completion_ratio=0.5,
        gaze_missingness_reason="gaze.permission_denied",
    )

    Draft202012Validator(feature_schema(), format_checker=FormatChecker()).validate(record)
    assert record["modality"] == "non_gaze_only"
    assert record["source_event_count"] == 3
    assert record["features"] == {
        "interaction.click_count": 1,
        "interaction.scroll_distance_px": 100.0,
        "survey.completion_ratio": 0.5,
    }
    assert record["quality"]["missingness"] == ["gaze.permission_denied"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("event_id", "", "event_id must be a non-empty string"),
        ("payload", [], "payload must be an object"),
        ("occurred_at", "2026-01-01T10:00:00", "occurred_at must include a UTC offset"),
        ("occurred_at", "not-a-time", "occurred_at must be a valid RFC 3339 timestamp"),
        ("schema_version", "9.0.0", "unsupported schema_version: '9.0.0'"),
    ],
)
def test_malformed_events_are_rejected_deterministically(field, value, message):
    event = load_events()[0].copy()
    event[field] = value
    with pytest.raises(ValueError, match=message):
        validate_event(event)


def test_duplicate_event_with_conflicting_content_is_rejected():
    event = load_events()[0]
    conflicting = {**event, "payload": {"target_aoi_id": "different"}}
    with pytest.raises(ValueError, match="conflicting duplicate event_id"):
        deduplicate_events([event, conflicting])


def test_same_event_id_in_different_sessions_is_not_cross_session_deduplicated():
    event = load_events()[0]
    other_session = {**event, "session_id": "session-synthetic-nongaze-0002"}
    assert len(deduplicate_events([event, other_session])) == 2


def test_empty_input_requires_explicit_context_and_is_schema_valid():
    record = build_non_gaze_feature_record(
        [],
        experience_id="exp-demo-store",
        study_id="study-product-evaluation",
        session_id="session-empty-0001",
        gaze_missingness_reason="gaze.unavailable",
    )
    Draft202012Validator(feature_schema(), format_checker=FormatChecker()).validate(record)
    assert record["source_event_count"] == 0
    assert record["features"]["interaction.click_count"] == 0
    assert record["quality"]["missingness"] == ["gaze.unavailable"]


def test_missing_gaze_is_not_zero_and_measured_zero_is_preserved():
    record = build_non_gaze_feature_record(
        [],
        experience_id="exp-demo-store",
        study_id="study-product-evaluation",
        session_id="session-zero-0001",
        survey_completion_ratio=0.0,
    )
    assert record["features"]["survey.completion_ratio"] == 0.0
    assert record["quality"]["gaze_available"] is False
    assert record["quality"]["missingness"] == ["gaze.unavailable"]


def test_repeated_inputs_reproduce_identical_feature_record():
    events = load_events()
    first = build_non_gaze_feature_record(events, survey_completion_ratio=1.0)
    second = build_non_gaze_feature_record(list(reversed(events)), survey_completion_ratio=1.0)
    assert first == second
