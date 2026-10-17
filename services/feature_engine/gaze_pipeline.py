"""P3-owned end-to-end processing for one study-scoped trial.

This module deliberately composes the existing provider adapter, quality,
association, fixation, AOI, metric, and FeatureRecord boundaries. It does not
introduce another gaze representation or persist captured video.
"""

from __future__ import annotations

from typing import Any

from services.feature_engine.gaze_metrics import build_gaze_feature_record, compute_gaze_metrics
from services.gaze_engine.adapter import ProviderSampleAdapter
from services.gaze_engine.context import TrialObservationContext, validate_observation_association
from services.gaze_engine.fixation import (
    detect_fixations_from_association,
    map_fixations_to_aois,
)
from services.gaze_engine.quality import GazeQualityAssessment, evaluate_gaze_quality

DEFAULT_UNAVAILABLE_REASON = "gaze.unavailable"


def process_trial_gaze(
    provider_samples: list[dict[str, Any]],
    *,
    experience_id: str,
    session_id: str,
    study_id: str,
    trial_id: str,
    aoi_set_version: str,
    observation_context: TrialObservationContext,
    geometry_snapshots: list[dict[str, Any]],
    events: list[dict[str, Any]],
    start_event: dict[str, Any] | list[dict[str, Any]] | None,
    requested_aoi_id: str | None,
    viewport_width_px: float | None = None,
    viewport_height_px: float | None = None,
    gaze_available: bool = True,
    gaze_missingness: str | None = None,
    calibration_status: str = "not_required",
    feature_set_version: str = "1.0.0",
    config_version: str | None = None,
    survey_completion_ratio: float | None = None,
) -> dict[str, Any]:
    """Process one explicitly scoped trial and return a FeatureRecord.

    Provider samples are normalized before quality assessment. The association
    contract then validates session/trial/window membership before fixation
    detection. AOI mapping is pinned to the context's study and AOI-set
    version. Camera denial bypasses provider processing and produces only the
    existing non-gaze features.
    """

    if not isinstance(observation_context, TrialObservationContext):
        raise TypeError("observation_context must be a validated TrialObservationContext")
    if (
        observation_context.session_id,
        observation_context.study_id,
        observation_context.trial_id,
        observation_context.aoi_set_version,
    ) != (session_id, study_id, trial_id, aoi_set_version):
        raise ValueError("trial processing context does not match the requested identity")

    records: list[dict[str, Any]]
    if not gaze_available:
        records = []
    elif provider_samples:
        if viewport_width_px is None or viewport_height_px is None:
            raise ValueError("viewport dimensions are required when provider samples are supplied")
        records = ProviderSampleAdapter().normalize_batch(
            provider_samples,
            session_id=session_id,
            viewport_width_px=viewport_width_px,
            viewport_height_px=viewport_height_px,
            calibration_status=calibration_status,
        )
    else:
        records = []

    quality: GazeQualityAssessment = evaluate_gaze_quality(records)
    association = {
        "schema_version": "1.0.0",
        "association_id": f"assoc-{session_id}-{study_id}-{trial_id}",
        "session_id": session_id,
        "study_id": study_id,
        "trial_id": trial_id,
        "aoi_set_version": aoi_set_version,
        "window_start": observation_context.window_start,
        "window_end": observation_context.window_end,
        "gaze_records": records,
    }
    validated_context, _ = validate_observation_association(association)

    quality_reason = gaze_missingness
    if not gaze_available:
        quality_reason = quality_reason or "gaze.permission_denied"
    elif quality.quality_status != "usable":
        quality_reason = quality_reason or (quality.missingness[0] if quality.missingness else DEFAULT_UNAVAILABLE_REASON)

    metrics_available = gaze_available and quality.quality_status == "usable"
    fixations = detect_fixations_from_association(association) if metrics_available else []
    assignments = (
        map_fixations_to_aois(
            fixations,
            session_id,
            geometry_snapshots,
            study_id=study_id,
            aoi_set_version=aoi_set_version,
        )
        if metrics_available
        else []
    )
    metrics = compute_gaze_metrics(
        fixations,
        assignments,
        session_id=session_id,
        study_id=study_id,
        aoi_set_version=aoi_set_version,
        requested_aoi_id=requested_aoi_id,
        start_event=start_event,
        gaze_available=metrics_available,
        gaze_missingness=quality_reason,
        observation_context=validated_context,
    )
    return build_gaze_feature_record(
        events,
        metrics,
        experience_id=experience_id,
        study_id=study_id,
        session_id=session_id,
        aoi_set_version=aoi_set_version,
        feature_set_version=feature_set_version,
        config_version=config_version,
        gaze_available=gaze_available,
        calibration_status=quality.calibration_status,
        gaze_missingness_reason=quality_reason,
        survey_completion_ratio=survey_completion_ratio,
    )
