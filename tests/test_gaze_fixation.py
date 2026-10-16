from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from services.gaze_engine.adapter import GazeNormalizationError, normalize_provider_samples
from services.gaze_engine.fixation import (
    detect_fixations,
    map_fixations_to_aois,
    map_gaze_to_aois,
)

SESSION_ID = "session-fixation-0001"
VIEWPORT = {"viewport_width_px": 100, "viewport_height_px": 100}


def provider_sample(
    sample_id: str,
    offset_ms: int,
    *,
    x: float = 25,
    y: float = 25,
    valid: bool = True,
) -> dict:
    return {
        "schema_version": "1.0.0",
        "provider": "synthetic-provider",
        "provider_version": "fixture-1",
        "sample_id": sample_id,
        "capture_time_ms": offset_ms,
        "occurred_at": (
            datetime(2026, 1, 1, 10, 0, tzinfo=UTC) + timedelta(milliseconds=offset_ms)
        ).isoformat().replace("+00:00", "Z"),
        "x_px": x,
        "y_px": y,
        "valid": valid,
        "quality": {"confidence": 0.9, "flags": []},
    }


def records(samples: list[dict]) -> list[dict]:
    return normalize_provider_samples(samples, session_id=SESSION_ID, **VIEWPORT)


def snapshot(rectangles: list[dict], captured_at: str = "2026-01-01T09:59:00Z") -> dict:
    return {
        "schema_version": "1.0.0",
        "snapshot_id": "geometry-1",
        "session_id": SESSION_ID,
        "captured_at": captured_at,
        "aoi_set_version": "aoi-v1",
        "viewport_width_px": 100,
        "viewport_height_px": 100,
        "scroll_x_px": 0,
        "scroll_y_px": 0,
        "zoom": 1,
        "rectangles": rectangles,
    }


def rectangle(aoi_id: str, left: float, top: float, right: float, bottom: float, priority: int = 0) -> dict:
    return {
        "aoi_id": aoi_id,
        "left_px": left,
        "top_px": top,
        "right_px": right,
        "bottom_px": bottom,
        "priority": priority,
    }


def test_detects_deterministic_dispersion_duration_fixation():
    input_samples = [
        provider_sample("s2", 200, x=26, y=25),
        provider_sample("s0", 0),
        provider_sample("s1", 100, x=24, y=25),
    ]
    first = detect_fixations(records(input_samples))
    second = detect_fixations(records(input_samples))
    assert first == second
    assert len(first) == 1
    assert first[0].sample_ids == ("s0", "s1", "s2")
    assert first[0].duration_ms == 200
    assert first[0].x_normalized == pytest.approx(0.25)


def test_gap_invalid_sample_and_insufficient_input_do_not_create_fixations():
    samples = records(
        [
            provider_sample("s0", 0),
            provider_sample("s1", 100),
            {**provider_sample("bad", 200), "valid": False},
            provider_sample("s2", 300),
            provider_sample("s3", 400),
        ]
    )
    assert detect_fixations(samples) == []
    assert detect_fixations(records([provider_sample("only", 0)])) == []


def test_out_of_order_input_is_sorted_and_duplicate_identity_is_rejected():
    ordered = records([provider_sample("s0", 0), provider_sample("s1", 100), provider_sample("s2", 200)])
    assert detect_fixations(list(reversed(ordered))) == detect_fixations(ordered)
    with pytest.raises(GazeNormalizationError, match="duplicate sample_id"):
        detect_fixations(ordered + [ordered[0]])


def test_missing_coordinates_and_timestamp_fail_closed():
    missing = records([{**provider_sample("missing", 0), "x_px": None, "y_px": None}])
    assert detect_fixations(missing) == []
    malformed = dict(missing[0])
    malformed["occurred_at"] = "not-a-timestamp"
    with pytest.raises(GazeNormalizationError, match="valid RFC 3339 timestamp"):
        detect_fixations([malformed])


def test_aoi_mapping_uses_edges_overlap_priority_and_outside_resolution():
    geometry = snapshot(
        [
            rectangle("low", 10, 10, 60, 60, priority=1),
            rectangle("high", 25, 25, 75, 75, priority=2),
        ]
    )
    sample_records = records(
        [
            provider_sample("interior", 0, x=30, y=30),
            provider_sample("left-edge", 100, x=25, y=25),
            provider_sample("right-edge", 200, x=75, y=75),
            provider_sample("outside", 300, x=90, y=90),
        ]
    )
    assignments = map_gaze_to_aois(sample_records, [geometry])
    assert [(item.observation_id, item.aoi_id) for item in assignments] == [
        ("interior", "high"),
        ("left-edge", "high"),
        ("right-edge", "aoi.unresolved"),
        ("outside", "aoi.unresolved"),
    ]


def test_equal_priority_overlap_uses_lexicographically_smallest_id():
    geometry = snapshot(
        [
            rectangle("zeta", 0, 0, 100, 100, priority=4),
            rectangle("alpha", 0, 0, 100, 100, priority=4),
        ]
    )
    assignment = map_gaze_to_aois(records([provider_sample("sample", 0)]), [geometry])[0]
    assert assignment.aoi_id == "alpha"


def test_invalid_geometry_no_aois_and_missing_snapshot_are_unresolved():
    invalid_geometry = snapshot(
        [rectangle("invalid", 20, 20, 10, 30), {"aoi_id": "malformed"}]
    )
    sample_records = records([provider_sample("sample", 0, x=25, y=25)])
    assignment = map_gaze_to_aois(sample_records, [invalid_geometry])[0]
    assert assignment.aoi_id == "aoi.unresolved"
    assert assignment.reason == "aoi.unresolved"
    assert map_gaze_to_aois(sample_records, [])[0].aoi_id == "aoi.unresolved"


def test_fixation_mapping_uses_latest_prior_snapshot_and_preserves_quality_boundary():
    geometry = snapshot([rectangle("target", 0, 0, 100, 100)])
    fixation = detect_fixations(
        records([provider_sample(f"s{i}", i * 100) for i in range(3)])
    )[0]
    assignment = map_fixations_to_aois([fixation], SESSION_ID, [geometry])[0]
    assert assignment.aoi_id == "target"
    assert assignment.snapshot_id == "geometry-1"


def test_non_gaze_empty_path_has_no_fabricated_results():
    assert detect_fixations([]) == []
    assert map_gaze_to_aois([], []) == []


def test_study_and_aoi_version_filters_prevent_cross_study_geometry_leakage():
    sample_records = records([provider_sample("sample", 100, x=25, y=25)])
    study_a = {
        **snapshot([rectangle("aoi-a", 0, 0, 50, 50)]),
        "schema_version": "2.0.0",
        "snapshot_id": "geometry-a",
        "study_id": "study-a",
        "aoi_set_version": "aoi-a",
    }
    study_b = {
        **snapshot([rectangle("aoi-b", 0, 0, 50, 50)]),
        "schema_version": "2.0.0",
        "snapshot_id": "geometry-b",
        "study_id": "study-b",
        "aoi_set_version": "aoi-b",
    }
    assignment = map_gaze_to_aois(
        sample_records,
        [study_b, study_a],
        study_id="study-a",
        aoi_set_version="aoi-a",
    )[0]
    assert assignment.aoi_id == "aoi-a"
    assert assignment.snapshot_id == "geometry-a"
    assert map_gaze_to_aois(sample_records, [study_b], study_id="study-a", aoi_set_version="aoi-a")[0].aoi_id == "aoi.unresolved"
