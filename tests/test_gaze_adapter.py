import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from services.gaze_engine.adapter import (
    DuplicateSampleIdentity,
    GazeNormalizationError,
    ProviderSampleAdapter,
    normalize_provider_sample,
    normalize_provider_samples,
)

ROOT = Path(__file__).resolve().parents[1]
SESSION_ID = "session-synthetic-gaze-0001"
VIEWPORT = {"viewport_width_px": 1024, "viewport_height_px": 768}


def load_fixture(name: str) -> dict:
    return json.loads((ROOT / "fixtures/gaze" / name).read_text())


def gaze_schema() -> dict:
    return json.loads((ROOT / "contracts/schemas/gaze-record.v1.schema.json").read_text())


def normalize(sample: dict) -> dict:
    return normalize_provider_sample(sample, session_id=SESSION_ID, **VIEWPORT)


def test_valid_provider_sample_normalizes_to_schema_valid_record():
    record = ProviderSampleAdapter().normalize(
        load_fixture("provider-sample-valid.json"), session_id=SESSION_ID, **VIEWPORT
    )
    Draft202012Validator(gaze_schema(), format_checker=FormatChecker()).validate(record)
    assert record == {
        "schema_version": "1.0.0",
        "sample_id": "sample-0001",
        "session_id": SESSION_ID,
        "occurred_at": "2026-01-01T10:00:01Z",
        "coordinate_space": "viewport_normalized",
        "x_normalized": 0.5,
        "y_normalized": 0.5,
        "confidence": 0.8,
        "valid": True,
        "calibration_status": "not_required",
        "quality_flags": [],
    }


def test_provider_invalid_sample_preserves_missing_coordinates_and_confidence():
    record = normalize(load_fixture("provider-sample-invalid.json"))
    assert record["valid"] is False
    assert record["x_normalized"] is None
    assert record["y_normalized"] is None
    assert record["confidence"] is None
    assert record["quality_flags"] == [
        "gaze.confidence_missing",
        "gaze.coordinates_missing",
        "provider.invalid",
        "provider.no_prediction",
    ]


@pytest.mark.parametrize(
    ("fixture", "message"),
    [
        ("provider-sample-out-of-range.json", "coordinates must be inside the viewport bounds"),
        ("provider-sample-malformed-time.json", "valid RFC 3339 timestamp"),
    ],
)
def test_malformed_or_out_of_range_samples_fail_closed(fixture: str, message: str):
    with pytest.raises(GazeNormalizationError, match=message):
        normalize(load_fixture(fixture))


def test_duplicate_sample_identity_is_rejected_within_session_batch():
    sample = load_fixture("provider-sample-valid.json")
    with pytest.raises(DuplicateSampleIdentity, match="duplicate sample_id"):
        normalize_provider_samples([sample, dict(sample)], session_id=SESSION_ID, **VIEWPORT)


def test_batch_normalization_is_deterministic_and_timestamp_ordered():
    first = load_fixture("provider-sample-valid.json")
    second = {**first, "sample_id": "sample-0002", "occurred_at": "2026-01-01T10:00:00Z"}
    batch = normalize_provider_samples([first, second], session_id=SESSION_ID, **VIEWPORT)
    repeated = normalize_provider_samples([first, second], session_id=SESSION_ID, **VIEWPORT)
    assert batch == repeated
    assert [record["sample_id"] for record in batch] == ["sample-0002", "sample-0001"]


def test_missing_required_provider_fields_are_rejected():
    sample = load_fixture("provider-sample-valid.json")
    del sample["quality"]
    with pytest.raises(GazeNormalizationError, match="missing required fields: quality"):
        normalize(sample)
