"""Versioned CSV adapter for external P4 predictive datasets.

This module intentionally does not produce canonical FeatureRecord v1 objects.
It produces the smaller internal record shape consumed by the existing P4
analysis engine and keeps participant identity available for grouped splits.
"""
from __future__ import annotations

import csv
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DATASET_ADAPTER_VERSION = "p4-external-csv/1.0.0"
_MISSING = {"", "na", "n/a", "nan", "null", "none", "missing"}
_SUSPICIOUS_TOKENS = (
    "outcome", "target", "label", "result", "post", "final", "success", "effectiveness",
)


class ExternalDatasetError(ValueError):
    """Actionable, stable error raised before an external dataset is accepted."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class ExternalDatasetConfig:
    dataset_id: str
    participant_column: str
    target_column: str
    predictor_columns: tuple[str, ...]
    session_column: str | None = None
    modality: str | None = None
    source: str | None = None
    feature_set_version: str = DATASET_ADAPTER_VERSION

    def __post_init__(self) -> None:
        text_fields = {
            "dataset_id": self.dataset_id,
            "participant_column": self.participant_column,
            "target_column": self.target_column,
        }
        for name, value in text_fields.items():
            if not isinstance(value, str) or not value.strip():
                raise ExternalDatasetError("invalid_configuration", f"{name} must be non-empty")
        if not self.predictor_columns or any(
            not isinstance(name, str) or not name.strip() for name in self.predictor_columns
        ):
            raise ExternalDatasetError(
                "invalid_configuration", "predictor_columns must contain non-empty names"
            )
        if len(set(self.predictor_columns)) != len(self.predictor_columns):
            raise ExternalDatasetError("invalid_configuration", "predictor_columns must be unique")
        if self.session_column is not None and not self.session_column.strip():
            raise ExternalDatasetError("invalid_configuration", "session_column must be non-empty")
        if self.target_column in self.predictor_columns:
            raise ExternalDatasetError(
                "target_leakage", "target_column cannot also be a predictor column",
                details={"target_column": self.target_column},
            )
        reserved = {self.participant_column, self.target_column}
        if self.session_column:
            reserved.add(self.session_column)
        overlap = sorted(reserved.intersection(self.predictor_columns))
        if overlap:
            raise ExternalDatasetError(
                "invalid_configuration", "identity columns cannot be predictors",
                details={"columns": overlap},
            )


@dataclass(frozen=True)
class ExternalDatasetImport:
    records: tuple[dict[str, Any], ...]
    diagnostics: dict[str, Any]
    config: ExternalDatasetConfig


def _is_missing(value: str | None) -> bool:
    return value is None or value.strip().lower() in _MISSING


def _column_type(values: list[Any]) -> str:
    observed = [value for value in values if value is not None]
    if not observed:
        return "missing"
    if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in observed):
        return "numeric"
    return "text"


def _suspicious_columns(config: ExternalDatasetConfig) -> list[str]:
    target_tokens = {token for token in config.target_column.lower().replace("-", "_").split("_") if token}
    suspicious = []
    for name in config.predictor_columns:
        normalized = name.lower().replace("-", "_")
        if normalized == config.target_column.lower() or any(
            token in normalized or token in target_tokens for token in _SUSPICIOUS_TOKENS
        ):
            suspicious.append(name)
    return suspicious


def import_csv(path: str | Path, config: ExternalDatasetConfig) -> ExternalDatasetImport:
    """Read and validate one CSV without logging raw rows or participant IDs."""
    source_path = str(path)
    file_path = Path(path)
    if not file_path.is_file():
        raise ExternalDatasetError(
            "source_file_not_found", "External dataset CSV file was not found",
            details={"source_file": source_path},
        )

    try:
        handle = file_path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise ExternalDatasetError(
            "source_file_unreadable", "External dataset CSV file could not be opened",
            details={"source_file": source_path},
        ) from exc

    with handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        required = {config.participant_column, config.target_column, *config.predictor_columns}
        if config.session_column:
            required.add(config.session_column)
        missing_columns = sorted(required - set(columns))
        if missing_columns:
            raise ExternalDatasetError(
                "missing_required_columns",
                "External dataset is missing required columns: " + ", ".join(missing_columns),
                details={"missing_columns": missing_columns, "source_file": source_path},
            )

        total = accepted = 0
        rejection_counts: Counter[str] = Counter()
        records: list[dict[str, Any]] = []
        participant_ids: set[str] = set()
        repeated_participants: Counter[str] = Counter()
        participant_sessions: set[tuple[str, str | None]] = set()
        missing_predictors = Counter()
        target_distribution: Counter[str] = Counter()
        feature_values: dict[str, list[Any]] = {name: [] for name in config.predictor_columns}
        feature_types: dict[str, str] = {}

        for row_number, row in enumerate(reader, start=2):
            total += 1
            participant = (row.get(config.participant_column) or "").strip()
            session = (row.get(config.session_column) or "").strip() if config.session_column else None
            if not participant:
                rejection_counts["missing_participant_id"] += 1
                continue
            if config.session_column and not session:
                rejection_counts["missing_session_id"] += 1
                continue
            identity = (participant, session)
            if identity in participant_sessions:
                rejection_counts["duplicate_participant_session_row"] += 1
                continue

            raw_target = row.get(config.target_column)
            if _is_missing(raw_target):
                rejection_counts["missing_target"] += 1
                continue
            target = _parse_target(raw_target)

            parsed: dict[str, Any] = {}
            row_missing_predictors: list[str] = []
            row_feature_values: dict[str, float | None] = {}
            invalid_predictor = False
            for name in config.predictor_columns:
                raw_value = row.get(name)
                if _is_missing(raw_value):
                    value = None
                    row_missing_predictors.append(name)
                else:
                    try:
                        value = float(raw_value)  # type: ignore[arg-type]
                    except (TypeError, ValueError):
                        invalid_predictor = True
                        break
                    if not math.isfinite(value):
                        invalid_predictor = True
                        break
                parsed[name] = _feature_value(name, value, config.modality)
                row_feature_values[name] = value
            if invalid_predictor:
                rejection_counts["invalid_non_numeric_predictor"] += 1
                continue
            # The existing P4 engine resolves both target and predictors from
            # record["features"]. Keep the target there for compatibility, but
            # never include it in the configured predictor set.
            parsed[config.target_column] = target

            record: dict[str, Any] = {
                "record_id": f"{config.dataset_id}:row:{row_number}",
                "participant_id": participant,
                "study_id": config.dataset_id,
                "feature_set_version": config.feature_set_version,
                "modality": [config.modality] if config.modality else ["external"],
                "features": parsed,
                "external_dataset": {
                    "dataset_id": config.dataset_id,
                    "source": config.source or source_path,
                    "adapter_version": DATASET_ADAPTER_VERSION,
                },
                "target": target,
            }
            if session is not None:
                record["session_id"] = session
            records.append(record)
            accepted += 1
            participant_ids.add(participant)
            if participant in repeated_participants:
                repeated_participants[participant] += 1
            else:
                repeated_participants[participant] = 1
            participant_sessions.add(identity)
            target_distribution[str(target)] += 1
            for name in row_missing_predictors:
                missing_predictors[name] += 1
            for name, value in row_feature_values.items():
                feature_values[name].append(value)

        for name, values in feature_values.items():
            feature_types[name] = _column_type(values)

    suspicious = _suspicious_columns(config)
    warnings: list[str] = []
    if suspicious:
        warnings.append(
            "Potential target/post-outcome leakage in predictor names; review before training: "
            + ", ".join(suspicious)
        )
    repeated_ids = sum(1 for count in repeated_participants.values() if count > 1)
    if repeated_ids:
        warnings.append(
            f"{repeated_ids} participant ID(s) have repeated accepted rows; grouped evaluation is required."
        )
    if len(participant_ids) < 3:
        warnings.append("Fewer than three participants are available for grouped holdout evaluation.")
    if accepted < 10:
        warnings.append("Fewer than ten accepted samples are available; predictive estimates may be unstable.")
    if len(target_distribution) > 1:
        largest = max(target_distribution.values())
        smallest = min(target_distribution.values())
        if smallest and largest / smallest >= 4:
            warnings.append("Target classes are imbalanced; inspect class counts before classification.")

    diagnostics = {
        "dataset_id": config.dataset_id,
        "source_file": source_path,
        "adapter_schema_version": DATASET_ADAPTER_VERSION,
        "total_rows": total,
        "accepted_rows": accepted,
        "rejected_rows": total - accepted,
        "rejection_counts": dict(sorted(rejection_counts.items())),
        "participant_count": len(participant_ids),
        "session_count": len({record.get("session_id") for record in records if record.get("session_id")}),
        "target_distribution": dict(sorted(target_distribution.items())),
        "missing_values_per_predictor": dict(sorted(missing_predictors.items())),
        "feature_column_types": feature_types,
        "repeated_participant_id_count": repeated_ids,
        "suspicious_predictor_columns": suspicious,
        "warnings": warnings,
    }
    return ExternalDatasetImport(tuple(records), diagnostics, config)


def _parse_target(raw: str | None) -> float | str:
    assert raw is not None
    text = raw.strip()
    try:
        value = float(text)
    except ValueError:
        return text
    return value if math.isfinite(value) else text


def _feature_value(name: str, value: float | None, modality: str | None) -> Any:
    if modality and modality.lower() == "gaze":
        return {"value": value, "modality": "gaze"}
    return value
