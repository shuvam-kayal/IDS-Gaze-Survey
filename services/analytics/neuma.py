"""NeuMa page-exposure loader and leakage-safe P4 training helpers.

The published BIDS export contains eye-tracker samples and click/page markers,
but not product AOIs or click coordinates.  This module therefore supports the
verified page-exposure target only: whether at least one left-click occurred
before the page exposure ended.  Product-level training is rejected explicitly.
"""
from __future__ import annotations

import array
import csv
import json
import math
import re
from pathlib import Path
from statistics import fmean, stdev
from typing import Any

from .advanced import run_experiment
from .capabilities import cross_validation, predict_with_saved_result

NEUMA_SCHEMA_VERSION = "neuma-page-exposure/1.0.0"
PREDICTION_WINDOW_SECONDS = 2.0
_PAGE_RE = re.compile(r"FYLLADIO_(\d+)")
_GAZE_CHANNELS = ("left_x", "left_y", "left_pupil", "right_x", "right_y", "right_pupil")


class NeuMaDataError(ValueError):
    """Actionable error for an invalid or unsupported NeuMa export."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _read_events(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
    except OSError as exc:
        raise NeuMaDataError("events_unreadable", f"Could not read {path}: {exc}") from exc
    required = {"onset", "duration", "sample", "value"}
    if not required.issubset(rows[0] if rows else set()):
        raise NeuMaDataError("events_schema", f"{path} lacks required event columns")
    return rows


def _load_fdt(path: Path) -> list[float]:
    try:
        with path.open("rb") as handle:
            values = array.array("f")
            values.fromfile(handle, path.stat().st_size // values.itemsize)
            if values.itemsize != 4:
                raise NeuMaDataError("fdt_format", f"Unsupported float width in {path}")
            return values.tolist()
    except (OSError, EOFError) as exc:
        raise NeuMaDataError("fdt_unreadable", f"Could not read {path}: {exc}") from exc


def _channel_values(values: list[float], start: int, stop: int, channel: int) -> list[float]:
    return [values[index] for index in range(start * 6 + channel, stop * 6, 6)]


def _summary(values: list[float]) -> tuple[float | None, float | None, float]:
    valid = [value for value in values if math.isfinite(value)]
    if not valid:
        return None, None, 0.0
    return fmean(valid), stdev(valid) if len(valid) > 1 else 0.0, len(valid) / len(values)


def _participant_id(path: Path) -> str:
    match = re.fullmatch(r"sub-(.+)", path.name)
    if not match:
        raise NeuMaDataError("participant_id", f"Invalid participant directory: {path}")
    return match.group(1)


def load_neuma_page_records(dataset_dir: str | Path, *, target: str = "selected_any") -> list[dict[str, Any]]:
    """Extract fixed-window page records without using post-click samples."""
    if target != "selected_any":
        raise NeuMaDataError(
            "unsupported_target",
            "NeuMa product-level targets are unavailable; only selected_any page exposure is supported",
        )
    root = Path(dataset_dir)
    if not root.is_dir():
        raise NeuMaDataError("dataset_not_found", f"NeuMa directory was not found: {root}")
    records: list[dict[str, Any]] = []
    for subject_dir in sorted(root.glob("sub-*/eye_tracker")):
        participant_id = _participant_id(subject_dir.parent)
        events_path = subject_dir / f"sub-{participant_id}_task-unnamed_events.tsv"
        fdt_path = subject_dir / f"sub-{participant_id}_task-unnamed_et.fdt"
        json_path = subject_dir / f"sub-{participant_id}_task-unnamed_et.json"
        for path in (events_path, fdt_path, json_path):
            if not path.is_file():
                raise NeuMaDataError("missing_file", f"Required NeuMa file is missing: {path}")
        events = _read_events(events_path)
        metadata = json.loads(json_path.read_text(encoding="utf-8"))
        srate = float(metadata.get("SamplingFrequency", 0))
        if srate <= 0:
            raise NeuMaDataError("sampling_rate", f"Invalid sampling rate in {json_path}")
        values = _load_fdt(fdt_path)
        sample_count = len(values) // len(_GAZE_CHANNELS)
        page_events = [(float(row["onset"]), int(_PAGE_RE.search(row["value"]).group(1))) for row in events if _PAGE_RE.search(row["value"])]
        click_times = [float(row["onset"]) for row in events if row["value"] == "MouseButtonLeft pressed"]
        eoe_times = [float(row["onset"]) for row in events if row["value"] == "EOE"]
        for ordinal, (onset, page_number) in enumerate(page_events):
            next_onset = page_events[ordinal + 1][0] if ordinal + 1 < len(page_events) else None
            end = next_onset or (eoe_times[0] if eoe_times else sample_count / srate)
            cutoff = onset + PREDICTION_WINDOW_SECONDS
            if end <= cutoff:
                continue
            first_click = next((click for click in click_times if onset <= click < end), None)
            if first_click is not None and first_click < cutoff:
                continue
            start_sample = max(0, min(sample_count, int(onset * srate)))
            stop_sample = max(start_sample + 1, min(sample_count, int(cutoff * srate)))
            if stop_sample <= start_sample:
                continue
            feature_values: dict[str, Any] = {
                "page_number": float(page_number),
            }
            valid_rates = []
            for channel, name in enumerate(_GAZE_CHANNELS):
                mean, sd, valid_rate = _summary(_channel_values(values, start_sample, stop_sample, channel))
                feature_values[f"gaze_{name}_mean"] = {"value": mean, "modality": "gaze", "quality": valid_rate}
                feature_values[f"gaze_{name}_sd"] = {"value": sd, "modality": "gaze", "quality": valid_rate}
                valid_rates.append(valid_rate)
            feature_values["gaze_valid_rate"] = {"value": fmean(valid_rates), "modality": "gaze", "quality": fmean(valid_rates)}
            selected = any(cutoff <= click < end for click in click_times)
            feature_values[target] = int(selected)
            records.append({
                "record_id": f"neuma:{participant_id}:page:{ordinal}",
                "participant_id": participant_id,
                "session_id": f"page-{ordinal}",
                "trial_id": f"page-{page_number}-{ordinal}",
                "study_id": "neuma-on004588",
                "feature_set_version": NEUMA_SCHEMA_VERSION,
                "modality": ["gaze", "interaction"],
                "features": feature_values,
                "target": int(selected),
                "neuma": {
                    "page_number": page_number,
                    "onset_s": onset,
                    "prediction_cutoff_s": cutoff,
                    "prediction_window_s": PREDICTION_WINDOW_SECONDS,
                },
            })
    if not records:
        raise NeuMaDataError("no_records", "No page exposure records were extracted from NeuMa")
    return records


def train_neuma_page_model(records: list[dict[str, Any]], *, seed: int = 7) -> dict[str, Any]:
    """Evaluate majority and logistic baselines using the existing grouped P4 engine."""
    predictors = [
        "page_number", "gaze_valid_rate",
        *[f"gaze_{channel}_{stat}" for channel in _GAZE_CHANNELS for stat in ("mean", "sd")],
    ]
    parameters = {
            "target": "selected_any",
            "features": predictors,
            "task": "classification",
            "models": ["logistic"],
            "seed": seed,
            "include_predictions": True,
            "intended_use": "exploratory research only; no individual-level decisions",
        }
    result = run_experiment(records, parameters, "best_available")
    if result.get("status") == "succeeded":
        result["grouped_cross_validation"] = cross_validation(
            records, {**parameters, "folds": 5}, "best_available"
        )
    result["neuma"] = {"schema_version": NEUMA_SCHEMA_VERSION, "prediction_unit": "participant x page exposure", "product_level_target_supported": False}
    return result


def save_neuma_artifact(path: str | Path, result: dict[str, Any]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps({"artifact_version": NEUMA_SCHEMA_VERSION, "result": result}, indent=2), encoding="utf-8")


def load_neuma_artifact(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("artifact_version") != NEUMA_SCHEMA_VERSION or not isinstance(payload.get("result"), dict):
        raise NeuMaDataError("artifact_schema", "Unsupported NeuMa model artifact")
    return payload["result"]


def predict_neuma_artifact(path: str | Path, records: list[dict[str, Any]]) -> dict[str, Any]:
    """Run inference through the existing reusable P4 saved-result path."""
    result = load_neuma_artifact(path)
    saved_result = {"results": {"ml_experiment": result}, "study_id": "neuma-on004588"}
    return predict_with_saved_result(saved_result, records)
