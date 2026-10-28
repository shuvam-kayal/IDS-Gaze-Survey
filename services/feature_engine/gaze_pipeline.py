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
from services.gaze_engine.quality import USABLE_UNVERIFIED, GazeQualityAssessment, evaluate_gaze_quality
from services.telemetry.ingestion import deduplicate_events

DEFAULT_UNAVAILABLE_REASON = "gaze.unavailable"


def _validated_bootstrap(bootstrap: dict[str, Any], *, session_id: str, experience_id: str) -> dict[str, dict[str, Any]]:
    if not isinstance(bootstrap, dict) or bootstrap.get("schema_version") != "1.0.0":
        raise ValueError("unsupported session bootstrap")
    if bootstrap.get("session_id") != session_id or bootstrap.get("experience_id") != experience_id:
        raise ValueError("session bootstrap context does not match processing request")
    eligible = bootstrap.get("eligible_studies")
    if not isinstance(eligible, list):
        raise TypeError("session bootstrap eligible_studies must be an array")
    by_id: dict[str, dict[str, Any]] = {}
    required = {"study_id", "config_version", "aoi_set_version", "question_set_version"}
    for study in eligible:
        if not isinstance(study, dict) or not required.issubset(study):
            raise ValueError("session bootstrap contains an invalid study assignment")
        study_id = study["study_id"]
        if not all(isinstance(study[field], str) and study[field] for field in required):
            raise ValueError("session bootstrap study assignment contains invalid values")
        if study_id in by_id:
            raise ValueError("session bootstrap contains duplicate study assignments")
        by_id[study_id] = study
    return by_id


def process_session_gaze(
    study_trials: list[dict[str, Any]],
    *,
    session_bootstrap: dict[str, Any],
    experience_id: str,
    session_id: str,
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Process multiple study-scoped trials from one bootstrap-scoped session.

    Each item in ``study_trials`` owns its provider samples, context, geometry,
    lifecycle start event, requested AOI, and camera state. Pinned versions are
    taken from the existing SessionBootstrap contract and cannot be overridden
    by a trial item. Events are filtered by their existing ``study_ids`` field.
    Results are returned in deterministic study-id order.
    """

    pinned = _validated_bootstrap(
        session_bootstrap, session_id=session_id, experience_id=experience_id
    )
    validated_events = deduplicate_events(events)
    if not isinstance(study_trials, list):
        raise TypeError("study_trials must be an array")
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    for trial in sorted(study_trials, key=lambda item: item.get("study_id", "") if isinstance(item, dict) else ""):
        if not isinstance(trial, dict) or not isinstance(trial.get("study_id"), str):
            raise TypeError("study trial requires study_id")
        study_id = trial["study_id"]
        if study_id in seen:
            raise ValueError("study trial inputs must be unique per study")
        seen.add(study_id)
        assignment = pinned.get(study_id)
        if assignment is None:
            raise ValueError(f"study {study_id!r} is not eligible in the session bootstrap")
        if trial.get("aoi_set_version") not in (None, assignment["aoi_set_version"]):
            raise ValueError("trial AOI-set version does not match the pinned study assignment")
        if trial.get("config_version") not in (None, assignment["config_version"]):
            raise ValueError("trial config version does not match the pinned study assignment")
        study_events = [
            event for event in validated_events
            if isinstance(event, dict)
            and event.get("session_id") == session_id
            and isinstance(event.get("study_ids"), list)
            and study_id in event["study_ids"]
        ]
        results.append(
            process_trial_gaze(
                trial.get("provider_samples", []),
                experience_id=experience_id,
                session_id=session_id,
                study_id=study_id,
                trial_id=trial["trial_id"],
                aoi_set_version=assignment["aoi_set_version"],
                observation_context=trial["observation_context"],
                geometry_snapshots=trial.get("geometry_snapshots", []),
                events=study_events,
                start_event=trial.get("start_event"),
                requested_aoi_id=trial.get("requested_aoi_id"),
                viewport_width_px=trial.get("viewport_width_px"),
                viewport_height_px=trial.get("viewport_height_px"),
                gaze_available=trial.get("gaze_available", True),
                gaze_missingness=trial.get("gaze_missingness"),
                calibration_status=trial.get("calibration_status", "not_required"),
                feature_set_version=trial.get("feature_set_version", "1.0.0"),
                config_version=assignment["config_version"],
                survey_completion_ratio=trial.get("survey_completion_ratio"),
            )
        )
    return results


def process_persisted_session_gaze(
    event_repository: Any,
    study_trials: list[dict[str, Any]],
    *,
    session_bootstrap: dict[str, Any],
    experience_id: str,
    session_id: str,
) -> list[dict[str, Any]]:
    """Process events retrieved from the existing telemetry repository.

    The repository supplies validated, durably ingested EventEnvelopes. Gaze
    provider samples remain transient structured inputs to the P3 pipeline;
    raw camera frames are neither accepted nor stored here.
    """

    if not hasattr(event_repository, "list_events"):
        raise TypeError("event_repository must provide list_events")
    events = event_repository.list_events(session_id)
    return process_session_gaze(
        study_trials,
        session_bootstrap=session_bootstrap,
        experience_id=experience_id,
        session_id=session_id,
        events=events,
    )


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
    events = deduplicate_events(events)

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
    quality_is_usable = quality.quality_status in {"usable", USABLE_UNVERIFIED}
    if not gaze_available:
        quality_reason = quality_reason or "gaze.permission_denied"
    elif not quality_is_usable:
        quality_reason = quality_reason or (quality.missingness[0] if quality.missingness else DEFAULT_UNAVAILABLE_REASON)
    elif quality.quality_status == USABLE_UNVERIFIED:
        quality_reason = quality_reason or "gaze.quality_unverified"

    metrics_available = gaze_available and quality_is_usable
    fixations = detect_fixations_from_association(association) if metrics_available else []
    assignments = (
        map_fixations_to_aois(
            fixations,
            session_id,
            geometry_snapshots,
            records=records,
            study_id=study_id,
            aoi_set_version=aoi_set_version,
        )
        if metrics_available
        else []
    )
    if metrics_available and not geometry_snapshots:
        metrics_available = False
        quality_reason = "gaze.geometry_unavailable"
    if metrics_available and fixations and not any(assignment.snapshot_id for assignment in assignments):
        metrics_available = False
        quality_reason = "gaze.geometry_unavailable"
    metrics = compute_gaze_metrics(
        fixations,
        assignments,
        session_id=session_id,
        study_id=study_id,
        aoi_set_version=aoi_set_version,
        requested_aoi_id=requested_aoi_id,
        start_event=start_event,
        gaze_available=metrics_available,
        gaze_missingness=quality_reason if not metrics_available else None,
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
