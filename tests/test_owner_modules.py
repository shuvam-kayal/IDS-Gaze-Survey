from services.analytics.descriptive import describe
from services.feature_engine.non_gaze import build_non_gaze_features
from services.gaze_engine.adapter import NotConfiguredGazeAdapter
from services.telemetry.ingestion import validate_event_shape


def test_descriptive_empty_and_nonempty():
    assert describe([]) == {"n": 0, "mean": None, "median": None}
    assert describe([1.0, 3.0]) == {"n": 2, "mean": 2.0, "median": 2.0}


def test_non_gaze_features_from_events():
    events = [
        {"event_type": "interaction.click", "payload": {}},
        {"event_type": "interaction.scroll", "payload": {"scroll_delta_px": 120}},
        {"event_type": "interaction.scroll", "payload": {"scroll_delta_px": -20}},
    ]
    result = build_non_gaze_features(events, survey_completion_ratio=None)
    assert result == {"interaction.click_count": 1, "interaction.scroll_distance_px": 100.0, "survey.completion_ratio": None}


def test_event_shape_helper():
    event = {"schema_version":"1.0.0", "event_id":"evt-1", "experience_id":"exp-1", "study_ids":[], "session_id":"session-1", "event_type":"interaction.click", "occurred_at":"2026-01-01T10:00:00Z", "payload":{}}
    assert validate_event_shape(event)
    assert not validate_event_shape({**event, "schema_version":"9.0.0"})


def test_gaze_adapter_fails_closed_until_configured():
    try:
        NotConfiguredGazeAdapter().normalize({}, session_id="session-1")
    except NotImplementedError:
        pass
    else:
        raise AssertionError("unconfigured adapter must not fabricate gaze samples")
