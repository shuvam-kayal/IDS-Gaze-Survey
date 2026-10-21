"""Adapters from the frozen P3 FeatureRecord v1 shape to the P4 engine."""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .engine import GAZE_WORDS, AnalysisError, finite

FEATURE_RECORD_SCHEMA_VERSION = "1.0.0"
_REQUIRED = {
    "schema_version", "feature_record_id", "experience_id", "study_id", "session_id",
    "feature_set_version", "config_version", "aoi_set_version", "modality", "window",
    "features", "quality", "source_event_count",
}


class TelemetryFeatureRecordProvider:
    """Read canonical P3 records through its persisted repository interface.

    ``session_ids_for_study`` must return only sessions the authenticated
    caller may analyze. The API router independently authorizes the study
    before calling this provider. P3 currently lists records by session, so
    this adapter fans out over that trusted session list and filters the
    requested feature-set version without changing P3 persistence code.
    """

    def __init__(
        self,
        telemetry_repository: Any,
        *,
        session_ids_for_study: Callable[[str], Sequence[str]],
    ) -> None:
        if not callable(getattr(telemetry_repository, "list_feature_records", None)):
            raise TypeError("telemetry_repository must provide list_feature_records")
        if not callable(session_ids_for_study):
            raise TypeError("session_ids_for_study must be callable")
        self._repository = telemetry_repository
        self._session_ids_for_study = session_ids_for_study

    def get_for_analysis(
        self, *, study_id: str, feature_set_version: str
    ) -> list[Mapping[str, Any]]:
        if not isinstance(study_id, str) or not study_id.strip():
            raise AnalysisError("invalid_study_id", "study_id must be a non-empty string")
        if not isinstance(feature_set_version, str) or not feature_set_version.strip():
            raise AnalysisError(
                "invalid_feature_set_version", "feature_set_version must be a non-empty string"
            )

        session_ids = self._session_ids_for_study(study_id)
        if isinstance(session_ids, (str, bytes)) or not isinstance(session_ids, Sequence):
            raise AnalysisError("invalid_session_scope", "authorized session lookup must return a list")
        if any(not isinstance(session_id, str) or not session_id.strip() for session_id in session_ids):
            raise AnalysisError("invalid_session_scope", "authorized session IDs must be non-empty strings")

        records_by_id: dict[str, Mapping[str, Any]] = {}
        for session_id in sorted(set(session_ids)):
            records = self._repository.list_feature_records(session_id, study_id=study_id)
            if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
                raise AnalysisError("invalid_feature_store_response", "P3 feature store must return a record list")
            for record in records:
                if not isinstance(record, Mapping):
                    raise AnalysisError("invalid_feature_record", "P3 feature store returned a non-object record")
                if record.get("study_id") != study_id or record.get("session_id") != session_id:
                    raise AnalysisError(
                        "feature_record_scope_mismatch",
                        "P3 feature store returned a record outside the authorized study/session scope",
                    )
                if record.get("feature_set_version") != feature_set_version:
                    continue
                validate_feature_record(
                    record, study_id=study_id, feature_set_version=feature_set_version
                )
                record_id = str(record["feature_record_id"])
                existing = records_by_id.get(record_id)
                if existing is not None and dict(existing) != dict(record):
                    raise AnalysisError(
                        "feature_record_identity_conflict",
                        "P3 feature store returned conflicting content for one FeatureRecord ID",
                    )
                records_by_id[record_id] = record
        return [records_by_id[key] for key in sorted(records_by_id)]


def _is_gaze_feature(name: str, metric: Mapping[str, Any]) -> bool:
    modality = metric.get("modality")
    return modality == "gaze" or any(token in name.lower() for token in GAZE_WORDS)


def validate_feature_record(record: Mapping[str, Any], *, study_id: str, feature_set_version: str) -> None:
    missing = _REQUIRED - record.keys()
    if missing:
        raise AnalysisError("invalid_feature_record", "FeatureRecord v1 is missing: " + ", ".join(sorted(missing)))
    if record["schema_version"] != FEATURE_RECORD_SCHEMA_VERSION:
        raise AnalysisError("unsupported_feature_record_version", "Only FeatureRecord schema 1.0.0 is supported")
    if record.keys() - _REQUIRED:
        raise AnalysisError("invalid_feature_record", "FeatureRecord contains fields outside the frozen v1 schema")
    if record["study_id"] != study_id:
        raise AnalysisError("feature_record_scope_mismatch", "FeatureRecord study_id does not match the request")
    if record["feature_set_version"] != feature_set_version:
        raise AnalysisError("feature_version_mismatch", "FeatureRecord feature_set_version does not match the request")
    for field in ("feature_record_id", "experience_id", "session_id", "feature_set_version"):
        if not isinstance(record[field], str) or not record[field].strip():
            raise AnalysisError("invalid_feature_record", f"FeatureRecord {field} must be a non-empty string")
    for field in ("config_version", "aoi_set_version"):
        if record[field] is not None and not isinstance(record[field], str):
            raise AnalysisError("invalid_feature_record", f"FeatureRecord {field} must be a string or null")
    if not isinstance(record["modality"], str) or record["modality"] not in {"gaze_and_non_gaze", "non_gaze_only"}:
        raise AnalysisError("invalid_feature_record", "FeatureRecord modality is not a frozen v1 value")
    if not isinstance(record["features"], Mapping) or not isinstance(record["quality"], Mapping):
        raise AnalysisError("invalid_feature_record", "FeatureRecord features and quality must be objects")
    quality = record["quality"]
    if {"gaze_available", "missingness", "calibration_status"} - quality.keys():
        raise AnalysisError("invalid_feature_record", "FeatureRecord quality is missing required v1 fields")
    if not isinstance(quality.get("gaze_available"), bool) or not isinstance(quality.get("missingness"), list):
        raise AnalysisError("invalid_feature_record", "FeatureRecord quality is missing gaze availability or missingness")
    if not all(isinstance(code, str) for code in quality["missingness"]):
        raise AnalysisError("invalid_feature_record", "FeatureRecord missingness values must be reason-code strings")
    if quality.get("calibration_status") is not None and not isinstance(quality["calibration_status"], str):
        raise AnalysisError("invalid_feature_record", "FeatureRecord calibration_status must be a string or null")
    if record["window"] is not None and not isinstance(record["window"], Mapping):
        raise AnalysisError("invalid_feature_record", "FeatureRecord window must be an object or null")
    if not isinstance(record["source_event_count"], int) or isinstance(record["source_event_count"], bool) or record["source_event_count"] < 0:
        raise AnalysisError("invalid_feature_record", "FeatureRecord source_event_count must be a non-negative integer")


def to_engine_record(
    record: Mapping[str, Any], *, study_id: str, feature_set_version: str,
    heatmap_input: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Translate P3 fields without inventing participant, quality, or spatial data."""
    validate_feature_record(record, study_id=study_id, feature_set_version=feature_set_version)
    modality = record["modality"]
    features: dict[str, Any] = {}
    for name, value in record["features"].items():
        if isinstance(value, Mapping) and "value" in value:
            metric = dict(value)
            if metric.get("requested_aoi_id") is not None:
                metric["aoi_id"] = metric["requested_aoi_id"]
            if _is_gaze_feature(str(name), metric):
                metric["modality"] = "gaze"
                if not record["quality"]["gaze_available"]:
                    # Preserve missingness as null; never turn unavailable gaze into zero.
                    metric["value"] = None
            else:
                metric["modality"] = "non_gaze"
            features[str(name)] = metric
        else:
            features[str(name)] = value

    adapted: dict[str, Any] = {
        "record_id": record["feature_record_id"],
        "study_id": record["study_id"],
        "session_id": record["session_id"],
        "feature_set_version": record["feature_set_version"],
        "modality": ["gaze", "interaction"] if modality == "gaze_and_non_gaze" else ["interaction"],
        "features": features,
        "quality": dict(record["quality"]),
        "missingness": list(record["quality"].get("missingness", [])),
        "source_event_count": record["source_event_count"],
        "aoi_set_version": record["aoi_set_version"],
    }
    if heatmap_input is not None:
        adapted["spatial"] = validate_heatmap_input(heatmap_input, record)
    return adapted


def validate_heatmap_input(value: Mapping[str, Any], record: Mapping[str, Any]) -> dict[str, Any]:
    """Convert separately supplied P4 heatmap observations, never FeatureRecord.spatial."""
    required = {"schema_version", "study_id", "feature_record_id", "session_id", "geometry_snapshot_id", "coordinate_system", "quality", "points", "geometry_version", "aoi_geometry"}
    if not isinstance(value, Mapping):
        raise AnalysisError("invalid_heatmap_input", "HeatmapInput v1 must be an object")
    if required - value.keys():
        raise AnalysisError("invalid_heatmap_input", "HeatmapInput v1 is missing: " + ", ".join(sorted(required - value.keys())))
    if value.keys() - required:
        raise AnalysisError("invalid_heatmap_input", "HeatmapInput contains fields outside its versioned schema")
    if (
        value["schema_version"] != "1.0.0"
        or value["study_id"] != record["study_id"]
        or value["feature_record_id"] != record["feature_record_id"]
        or value["session_id"] != record["session_id"]
        or not isinstance(value["geometry_snapshot_id"], str)
        or not value["geometry_snapshot_id"].strip()
        or (
            record["aoi_set_version"] is not None
            and value["geometry_version"] != record["aoi_set_version"]
        )
    ):
        raise AnalysisError(
            "heatmap_scope_mismatch",
            "HeatmapInput must match the canonical study, FeatureRecord, session and AOI-set version",
        )
    if not isinstance(value["points"], list) or not isinstance(value["aoi_geometry"], (dict, list)):
        raise AnalysisError("invalid_heatmap_input", "HeatmapInput points and AOI geometry have invalid shapes")
    quality = value["quality"]
    if quality is not None and (not finite(quality) or not 0 <= float(quality) <= 1):
        raise AnalysisError("invalid_heatmap_input", "HeatmapInput quality must be between 0 and 1 or null")
    if not isinstance(value["coordinate_system"], str) or not value["coordinate_system"].strip():
        raise AnalysisError("invalid_heatmap_input", "HeatmapInput coordinate_system must be a non-empty string")
    if value["geometry_version"] is not None and not isinstance(value["geometry_version"], str):
        raise AnalysisError("invalid_heatmap_input", "HeatmapInput geometry_version must be a string or null")
    if not all(isinstance(point, Mapping) and set(point) == {"x", "y"} and finite(point["x"]) and finite(point["y"]) for point in value["points"]):
        raise AnalysisError("invalid_heatmap_input", "HeatmapInput points must contain finite x/y coordinate objects")
    return {
        "points": value["points"], "quality": value["quality"],
        "coordinate_system": value["coordinate_system"],
        "geometry_version": value["geometry_version"], "aoi_geometry": value["aoi_geometry"],
    }


def adapt_records(
    records: Sequence[Mapping[str, Any]], *, study_id: str, feature_set_version: str,
    heatmap_inputs: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    heatmap_inputs = heatmap_inputs or {}
    return [
        to_engine_record(record, study_id=study_id, feature_set_version=feature_set_version,
                         heatmap_input=heatmap_inputs.get(str(record.get("feature_record_id"))))
        for record in records
    ]
