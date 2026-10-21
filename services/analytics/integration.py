"""Embeddable P4 API adapter for the shared FastAPI application."""
from __future__ import annotations

import csv
import io
import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response

from .capabilities import MODEL_REGISTRY
from .engine import ANALYSIS_VERSION, AnalysisError, analyze
from .feature_records import adapt_records
from .persistence import AnalysisRepository

_BASE_TYPES = {"descriptive", "correlation", "group_comparison", "classification", "regression", "clustering"}
_EXTENSION_TYPES = set(json.loads(Path(__file__).with_name("contracts").joinpath("analysis-extension.v1.schema.json").read_text(encoding="utf-8"))["properties"]["analysis_types"]["items"]["enum"])


class FeatureRecordProvider(Protocol):
    """P3-owned retrieval interface injected by the shared application."""

    def get_for_analysis(self, *, study_id: str, feature_set_version: str) -> Sequence[Mapping[str, Any]]: ...


class HeatmapInputProvider(Protocol):
    """Separate authorized P3 spatial/geometry bridge; no FeatureRecord.spatial field."""

    def get_for_feature_records(self, *, study_id: str, feature_record_ids: Sequence[str]) -> Mapping[str, Mapping[str, Any]]: ...


def _validate_v1(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict):
        raise AnalysisError("invalid_request", "AnalysisRequest v1 must be a JSON object")
    required = {"schema_version", "analysis_request_id", "study_id", "feature_set_version", "modality_policy", "analysis_types", "parameters"}
    allowed = required | {"requested_at"}
    if missing := required - request.keys():
        raise AnalysisError("missing_fields", "AnalysisRequest v1 is missing: " + ", ".join(sorted(missing)))
    if extra := request.keys() - allowed:
        raise AnalysisError("unknown_fields", "AnalysisRequest v1 has unsupported fields: " + ", ".join(sorted(extra)))
    if request["schema_version"] != "1.0.0":
        raise AnalysisError("unsupported_request_version", "Only frozen AnalysisRequest schema 1.0.0 is supported")
    for key in ("analysis_request_id", "study_id", "feature_set_version"):
        if not isinstance(request[key], str) or not request[key].strip():
            raise AnalysisError("invalid_request", f"{key} must be a non-empty string")
    if request["modality_policy"] not in {"best_available", "gaze_only", "non_gaze_only"}:
        raise AnalysisError("invalid_request", "modality_policy is not a frozen v1 value")
    types = request["analysis_types"]
    if not isinstance(types, list) or not types or any(not isinstance(item, str) for item in types) or set(types) - _BASE_TYPES:
        raise AnalysisError("invalid_request", "analysis_types must contain frozen AnalysisRequest v1 types")
    if not isinstance(request["parameters"], dict):
        raise AnalysisError("invalid_request", "parameters must be an object")
    ext = request["parameters"].get("p4_extension")
    if ext is not None:
        if not isinstance(ext, dict) or ext.get("schema_version") != "1.0.0" or set(ext) != {"schema_version", "analysis_types"}:
            raise AnalysisError("invalid_extension", "parameters.p4_extension must match P4 Analysis Extension v1")
        ext_types = ext["analysis_types"]
        if (
            not isinstance(ext_types, list)
            or not ext_types
            or any(not isinstance(item, str) for item in ext_types)
            or len(ext_types) != len(set(ext_types))
            or set(ext_types) - _EXTENSION_TYPES
        ):
            raise AnalysisError("invalid_extension", "P4 extension analysis_types contains unsupported or duplicate values")
    if request.get("requested_at") is not None:
        try:
            requested_at = datetime.fromisoformat(str(request["requested_at"]))
        except ValueError as exc:
            raise AnalysisError("invalid_request", "requested_at must be an ISO-8601 timestamp or null") from exc
        if "T" not in str(request["requested_at"]) or requested_at.tzinfo is None:
            raise AnalysisError("invalid_request", "requested_at must include a date, time, and timezone")
    return request


def _internal_request(request: dict[str, Any], records: Sequence[Mapping[str, Any]], heatmap_inputs: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    params = dict(request["parameters"])
    extension = params.pop("p4_extension", None) or {"analysis_types": []}
    requested = list(request["analysis_types"])
    internal_types: list[str] = []
    for name in requested:
        if name in {"classification", "regression"}:
            params["task"] = name
            internal_types.append("ml_experiment")
        else:
            internal_types.append(name)
    internal_types.extend(extension["analysis_types"])
    internal_types = list(dict.fromkeys(internal_types))
    if "heatmap" in internal_types and heatmap_inputs:
        # adapt_records attaches a separately versioned provider payload as an
        # ephemeral engine input; it never reads spatial from the canonical record.
        pass
    internal_records = adapt_records(
        records,
        study_id=request["study_id"],
        feature_set_version=request["feature_set_version"],
        heatmap_inputs=heatmap_inputs,
    )
    return {
        "request_id": request["analysis_request_id"],
        "study_id": request["study_id"],
        "feature_set_version": request["feature_set_version"],
        "modality_policy": request["modality_policy"],
        "analysis_types": internal_types,
        "parameters": params,
        "feature_records": internal_records,
    }


def _frozen_result(request: dict[str, Any], internal: dict[str, Any], records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    modalities = {record["modality"] for record in records}
    modality = "gaze_and_non_gaze" if "gaze_and_non_gaze" in modalities and request["modality_policy"] != "non_gaze_only" else "non_gaze_only"
    status = "insufficient_data" if internal["status"] in {"no_data", "insufficient_data"} else "succeeded"
    analyses = dict(internal["results"])
    missingness = sorted({code for record in records for code in record["quality"].get("missingness", [])})
    analyses["p4_provenance"] = {
        "analysis_version": ANALYSIS_VERSION,
        "feature_record_ids": [record["feature_record_id"] for record in records],
        "session_ids": sorted({record["session_id"] for record in records}),
        "modality_policy": request["modality_policy"],
        "quality": {
            "gaze_available_record_n": sum(record["quality"]["gaze_available"] for record in records),
            "gaze_unavailable_record_n": sum(not record["quality"]["gaze_available"] for record in records),
            "missingness_reason_codes": missingness,
            "per_feature_quality_score": "not supplied by FeatureRecord v1; no score inferred",
        },
        "warnings": internal["warnings"],
        "data_scope": internal["data_scope"],
        "metadata": internal["metadata"],
        "report": internal.get("report"),
    }
    return {
        "schema_version": "1.0.0",
        "analysis_id": internal["result_id"],
        "analysis_request_id": request["analysis_request_id"],
        "study_id": request["study_id"],
        "feature_set_version": request["feature_set_version"],
        "model_version": ANALYSIS_VERSION if any(x in {"classification", "regression"} for x in request["analysis_types"]) else None,
        "modality": modality,
        "status": status,
        "sample_size": internal["metadata"]["sample_size"],
        "results": analyses,
        "limitations": list(internal["limitations"]),
        "created_at": internal["generated_at"],
    }


def _queued_result(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "analysis_id": str(uuid.uuid4()),
        "analysis_request_id": request["analysis_request_id"],
        "study_id": request["study_id"],
        "feature_set_version": request["feature_set_version"],
        "model_version": None,
        "modality": "non_gaze_only" if request["modality_policy"] == "non_gaze_only" else "gaze_and_non_gaze",
        "status": "queued",
        "sample_size": 0,
        "results": {"progress": {"status": "queued"}},
        "limitations": ["Analysis is queued; no result values are available yet."],
        "created_at": datetime.now(UTC).isoformat(),
    }
def create_analytics_router(
    *,
    get_feature_provider: Callable[..., FeatureRecordProvider],
    get_repository: Callable[..., AnalysisRepository],
    get_study_authorizer: Callable[..., Callable[[str], bool]],
    get_export_authorizer: Callable[..., Callable[[str], bool]] | None = None,
    get_heatmap_provider: Callable[..., HeatmapInputProvider | None] | None = None,
) -> APIRouter:
    """Create a router for inclusion in services/api/app.py after owner review."""
    router = APIRouter(prefix="/v1/analytics", tags=["analytics"])

    @router.get("/models")
    def list_models() -> dict[str, Any]:
        return {"registry_version": "p4-model-registry/1.0.0", "models": MODEL_REGISTRY}

    @router.get("/feature-sets")
    def list_feature_sets(
        study_id: str = Query(..., min_length=1),
        provider: FeatureRecordProvider = Depends(get_feature_provider),  # noqa: B008
        authorize: Callable[[str], bool] = Depends(get_study_authorizer),  # noqa: B008
    ) -> dict[str, Any]:
        if not authorize(study_id):
            raise HTTPException(status_code=403, detail="Study access is not authorized")
        discover = getattr(provider, "get_available_feature_set_versions", None)
        if not callable(discover):
            raise HTTPException(status_code=503, detail="Feature version discovery is unavailable")
        return {"study_id": study_id, "feature_set_versions": discover(study_id=study_id)}

    def calculate(
        request: dict[str, Any], provider: FeatureRecordProvider,
        heatmap_provider: HeatmapInputProvider | None,
    ) -> dict[str, Any]:
        records = provider.get_for_analysis(study_id=request["study_id"], feature_set_version=request["feature_set_version"])
        heatmap_inputs: Mapping[str, Mapping[str, Any]] = {}
        requested_extensions = request["parameters"].get("p4_extension", {}).get("analysis_types", [])
        if heatmap_provider and "heatmap" in requested_extensions:
            heatmap_inputs = heatmap_provider.get_for_feature_records(
                study_id=request["study_id"],
                feature_record_ids=[str(row.get("feature_record_id")) for row in records],
            )
        internal = analyze(_internal_request(request, records, heatmap_inputs))
        return _frozen_result(request, internal, records)

    def complete_job(
        request: dict[str, Any], analysis_id: str,
        provider: FeatureRecordProvider, repository: AnalysisRepository,
        heatmap_provider: HeatmapInputProvider | None,
    ) -> None:
        current = repository.get(analysis_id)
        if current is None or current["status"] in {"succeeded", "failed", "insufficient_data"}:
            return
        running = {**current, "status": "running", "results": {"progress": {"status": "running"}}}
        repository.update(running)
        try:
            result = calculate(request, provider, heatmap_provider)
            result["analysis_id"] = analysis_id
            repository.update(result)
        except Exception:  # noqa: BLE001 - failed jobs must reach a terminal persisted status
            failed = {
                **running,
                "status": "failed",
                "results": {"error": {"code": "analysis_failed", "message": "The analysis failed; consult server diagnostics."}},
                "limitations": ["No analysis result was produced."],
                "created_at": datetime.now(UTC).isoformat(),
            }
            repository.update(failed)

    @router.post("/analyze")
    def run_analysis(
        payload: dict[str, Any],
        provider: FeatureRecordProvider = Depends(get_feature_provider),  # noqa: B008
        repository: AnalysisRepository = Depends(get_repository),  # noqa: B008
        authorize: Callable[[str], bool] = Depends(get_study_authorizer),  # noqa: B008
    ) -> dict[str, Any]:
        try:
            request = _validate_v1(payload)
            if not authorize(request["study_id"]):
                raise HTTPException(status_code=403, detail="Study access is not authorized")
            heatmap_provider = get_heatmap_provider() if get_heatmap_provider else None
            result = calculate(request, provider, heatmap_provider)
            return repository.save(request, result)
        except AnalysisError as exc:
            raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)}) from exc

    @router.post("/jobs", status_code=202)
    def submit_job(
        payload: dict[str, Any],
        background_tasks: BackgroundTasks,
        provider: FeatureRecordProvider = Depends(get_feature_provider),  # noqa: B008
        repository: AnalysisRepository = Depends(get_repository),  # noqa: B008
        authorize: Callable[[str], bool] = Depends(get_study_authorizer),  # noqa: B008
    ) -> dict[str, Any]:
        try:
            request = _validate_v1(payload)
            if not authorize(request["study_id"]):
                raise HTTPException(status_code=403, detail="Study access is not authorized")
            queued = _queued_result(request)
            stored = repository.save(request, queued)
            if stored["analysis_id"] == queued["analysis_id"]:
                heatmap_provider = get_heatmap_provider() if get_heatmap_provider else None
                background_tasks.add_task(complete_job, request, stored["analysis_id"], provider, repository, heatmap_provider)
            return stored
        except AnalysisError as exc:
            raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)}) from exc

    @router.get("/jobs/{analysis_id}")
    def get_job(
        analysis_id: str,
        repository: AnalysisRepository = Depends(get_repository),  # noqa: B008
        authorize: Callable[[str], bool] = Depends(get_study_authorizer),  # noqa: B008
    ) -> dict[str, Any]:
        result = repository.get(analysis_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Analysis job not found")
        if not authorize(result["study_id"]):
            raise HTTPException(status_code=403, detail="Study access is not authorized")
        return result

    @router.get("/results/{analysis_id}")
    def get_result(
        analysis_id: str,
        repository: AnalysisRepository = Depends(get_repository),  # noqa: B008
        authorize: Callable[[str], bool] = Depends(get_study_authorizer),  # noqa: B008
    ) -> dict[str, Any]:
        result = repository.get(analysis_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Analysis result not found")
        if not authorize(result["study_id"]):
            raise HTTPException(status_code=403, detail="Study access is not authorized")
        return result

    @router.get("/results")
    def list_results(
        study_id: str = Query(..., min_length=1), limit: int = Query(50, ge=1, le=100),
        cursor: str | None = None,
        repository: AnalysisRepository = Depends(get_repository),  # noqa: B008
        authorize: Callable[[str], bool] = Depends(get_study_authorizer),  # noqa: B008
    ) -> dict[str, Any]:
        if not authorize(study_id):
            raise HTTPException(status_code=403, detail="Study access is not authorized")
        try:
            return repository.list_page(study_id, limit, cursor)
        except AnalysisError as exc:
            raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)}) from exc

    @router.get("/compare")
    def compare_results(
        left_id: str = Query(..., min_length=1), right_id: str = Query(..., min_length=1),
        repository: AnalysisRepository = Depends(get_repository),  # noqa: B008
        authorize: Callable[[str], bool] = Depends(get_study_authorizer),  # noqa: B008
    ) -> dict[str, Any]:
        left, right = repository.get(left_id), repository.get(right_id)
        if not left or not right:
            raise HTTPException(status_code=404, detail="Both analysis results must exist")
        if not authorize(left["study_id"]) or not authorize(right["study_id"]):
            raise HTTPException(status_code=403, detail="Study access is not authorized")
        reasons = [key for key in ("study_id", "feature_set_version", "modality") if left[key] != right[key]]
        left_provenance = left["results"].get("p4_provenance", {})
        right_provenance = right["results"].get("p4_provenance", {})
        left_scope = left_provenance.get("data_scope", {})
        right_scope = right_provenance.get("data_scope", {})
        for field in ("analysis_types", "analysis_parameters"):
            if left_scope.get(field) != right_scope.get(field):
                reasons.append(f"{field} differs")
        left_filters = left_scope.get("filter_summary", {})
        right_filters = right_scope.get("filter_summary", {})
        if left_filters.get("selection_fingerprint") != right_filters.get("selection_fingerprint"):
            reasons.append("filter/time selection differs")
        if left_provenance.get("modality_policy") != right_provenance.get("modality_policy"):
            reasons.append("modality policy differs")
        left_features = left["results"].get("descriptive", {})
        right_features = right["results"].get("descriptive", {})
        deltas: dict[str, Any] = {}
        for name in sorted(left_features.keys() & right_features.keys()):
            a, b = left_features[name], right_features[name]
            if a.get("kind") == b.get("kind") == "numeric" and a.get("unit") == b.get("unit") and isinstance(a.get("mean"), (int, float)) and isinstance(b.get("mean"), (int, float)):
                deltas[name] = {"left_mean": a["mean"], "right_mean": b["mean"], "mean_delta": b["mean"] - a["mean"], "unit": a.get("unit")}
        return {"status": "not_comparable" if reasons else "comparable", "reasons": reasons, "left_analysis_id": left_id, "right_analysis_id": right_id, "descriptive_mean_differences": deltas, "warning": "Descriptive differences are not inferential tests or causal effects."}

    @router.get("/results/{analysis_id}/csv")
    def export_csv(
        analysis_id: str,
        repository: AnalysisRepository = Depends(get_repository),  # noqa: B008
        authorize: Callable[[str], bool] = Depends(get_export_authorizer or get_study_authorizer),  # noqa: B008
    ) -> Response:
        result = repository.get(analysis_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Analysis result not found")
        if not authorize(result["study_id"]):
            raise HTTPException(status_code=403, detail="Study access is not authorized")
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["feature", "kind", "n", "missing_n", "mean", "median", "unit"])
        summaries = result.get("results", {}).get("descriptive", {})
        for feature, value in summaries.items():
            if not isinstance(value, dict):
                continue
            row = [feature, value.get("kind"), value.get("n"), value.get("missing_n"), value.get("mean"), value.get("median"), value.get("unit")]
            writer.writerow(["'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value for value in row])
        return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="analysis-{analysis_id}.csv"', "Cache-Control": "no-store"})

    return router
