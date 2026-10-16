import json
from pathlib import Path

import pytest

from services.gaze_engine.adapter import GazeNormalizationError, normalize_provider_samples
from services.gaze_engine.quality import evaluate_gaze_quality

ROOT = Path(__file__).resolve().parents[1]
SESSION_ID = "session-quality-0001"
VIEWPORT = {"viewport_width_px": 1024, "viewport_height_px": 768}


def provider_sample(sample_id: str, timestamp: str, confidence: float | None = 0.5) -> dict:
    return {
        "schema_version": "1.0.0",
        "provider": "synthetic-provider",
        "provider_version": "fixture-1",
        "sample_id": sample_id,
        "capture_time_ms": 1000,
        "occurred_at": timestamp,
        "x_px": 512,
        "y_px": 384,
        "valid": True,
        "quality": {"confidence": confidence, "flags": []},
    }


def records(samples: list[dict]) -> list[dict]:
    return normalize_provider_samples(samples, session_id=SESSION_ID, **VIEWPORT)


def test_empty_input_is_explicitly_no_samples():
    assessment = evaluate_gaze_quality([])
    assert assessment.quality_status == "no_samples"
    assert assessment.calibration_status == "pending"
    assert assessment.missingness == ("gaze.no_samples",)


def test_insufficient_valid_samples_are_not_usable():
    assessment = evaluate_gaze_quality(
        records([provider_sample(f"sample-{i}", f"2026-01-01T10:00:0{i}Z") for i in range(2)])
    )
    assert assessment.quality_status == "insufficient_data"
    assert assessment.valid_sample_count == 2
    assert "quality.insufficient_samples" in assessment.quality_flags


def test_thresholds_are_inclusive_for_valid_fraction_and_confidence():
    assessment = evaluate_gaze_quality(
        records(
            [provider_sample(f"valid-{i}", f"2026-01-01T10:00:0{i}Z", 0.5) for i in range(3)]
            + [
                {
                    **provider_sample(f"invalid-{i}", f"2026-01-01T10:00:0{i + 3}Z"),
                    "valid": False,
                }
                for i in range(3)
            ]
        )
    )
    assert assessment.valid_fraction == 0.5
    assert assessment.mean_confidence == 0.5
    assert assessment.quality_status == "usable"


def test_missing_confidence_is_low_quality_not_invalid_gaze():
    normalized = records(
        [provider_sample(f"sample-{i}", f"2026-01-01T10:00:0{i}Z", None) for i in range(3)]
    )
    assert all(record["valid"] for record in normalized)
    assessment = evaluate_gaze_quality(normalized)
    assert assessment.quality_status == "low_quality"
    assert assessment.mean_confidence is None
    assert "quality.confidence_missing" in assessment.quality_flags


def test_invalid_only_input_is_insufficient_not_valid_gaze():
    samples = [{**provider_sample("invalid-0", "2026-01-01T10:00:00Z"), "valid": False}]
    assessment = evaluate_gaze_quality(records(samples))
    assert assessment.quality_status == "insufficient_data"
    assert assessment.valid_sample_count == 0
    assert "quality.no_valid_samples" in assessment.quality_flags


def test_missing_coordinates_are_not_converted_to_zero():
    samples = [
        {**provider_sample(f"sample-{i}", f"2026-01-01T10:00:0{i}Z"), "x_px": None, "y_px": None}
        for i in range(3)
    ]
    normalized = records(samples)
    assert all(record["x_normalized"] is None and record["y_normalized"] is None for record in normalized)
    assessment = evaluate_gaze_quality(normalized)
    assert assessment.quality_status == "insufficient_data"
    assert assessment.valid_sample_count == 0


def test_mixed_missing_confidence_is_explicitly_low_quality():
    assessment = evaluate_gaze_quality(
        records(
            [
                provider_sample("sample-0", "2026-01-01T10:00:00Z", 0.8),
                provider_sample("sample-1", "2026-01-01T10:00:01Z", None),
                provider_sample("sample-2", "2026-01-01T10:00:02Z", 0.8),
            ]
        )
    )
    assert assessment.mean_confidence == 0.8
    assert assessment.quality_status == "low_quality"
    assert "gaze.low_quality" in assessment.missingness


def test_low_confidence_is_distinguished_from_invalid_samples():
    assessment = evaluate_gaze_quality(
        records([provider_sample(f"sample-{i}", f"2026-01-01T10:00:0{i}Z", 0.49) for i in range(3)])
    )
    assert assessment.valid_sample_count == 3
    assert assessment.quality_status == "low_quality"
    assert "quality.low_confidence" in assessment.quality_flags


def test_calibration_status_is_reported_only_from_canonical_input():
    normalized = records(
        [provider_sample(f"sample-{i}", f"2026-01-01T10:00:0{i}Z") for i in range(3)]
    )
    for record in normalized:
        record["calibration_status"] = "passed"
    assessment = evaluate_gaze_quality(normalized)
    assert assessment.calibration_status == "passed"
    assert assessment.quality_status == "usable"


def test_invalid_canonical_shape_fails_closed_and_repeated_input_is_deterministic():
    normalized = records(
        [provider_sample(f"sample-{i}", f"2026-01-01T10:00:0{i}Z") for i in range(3)]
    )
    first = evaluate_gaze_quality(normalized)
    second = evaluate_gaze_quality(json.loads(json.dumps(normalized)))
    assert first == second
    invalid = dict(normalized[0])
    invalid["x_normalized"] = 2
    with pytest.raises(GazeNormalizationError, match="between 0 and 1"):
        evaluate_gaze_quality([invalid])
