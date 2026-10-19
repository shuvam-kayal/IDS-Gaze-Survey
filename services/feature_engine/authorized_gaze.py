"""Internal P3 handler for already-authorized gaze observations.

This module is a service boundary for the future API/integrator layer. It does
not authenticate callers, decide consent, resolve study configuration, or
trust browser-supplied context. The caller must provide an explicitly
validated server-side :class:`AuthorizedGazeContext`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.feature_engine.gaze_pipeline import process_trial_gaze
from services.gaze_engine.adapter import ProviderSampleAdapter
from services.gaze_engine.context import (
    TrialObservationContext,
    validate_observation_association,
)
from services.telemetry.persistence import TelemetryRepository


@dataclass(frozen=True)
class AuthorizedGazeContext:
    """Trusted context supplied by an authorized upstream service.

    This type describes the existing P3 pipeline inputs; it is not an
    authorization mechanism and must not be constructed directly from an
    untrusted browser request.
    """

    experience_id: str
    session_id: str
    study_id: str
    trial_id: str
    aoi_set_version: str
    observation_context: TrialObservationContext
    geometry_snapshots: list[dict[str, Any]]
    events: list[dict[str, Any]]
    start_event: dict[str, Any] | list[dict[str, Any]] | None
    requested_aoi_id: str | None
    viewport_width_px: float | None = None
    viewport_height_px: float | None = None
    gaze_available: bool = True
    gaze_missingness: str | None = None
    calibration_status: str = "not_required"
    feature_set_version: str = "1.0.0"
    config_version: str | None = None
    survey_completion_ratio: float | None = None

    def validate(self) -> None:
        for name in (
            "experience_id",
            "session_id",
            "study_id",
            "trial_id",
            "aoi_set_version",
            "feature_set_version",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty string")
        if not isinstance(self.observation_context, TrialObservationContext):
            raise TypeError("observation_context must be a validated TrialObservationContext")
        expected = (
            self.session_id,
            self.study_id,
            self.trial_id,
            self.aoi_set_version,
        )
        actual = (
            self.observation_context.session_id,
            self.observation_context.study_id,
            self.observation_context.trial_id,
            self.observation_context.aoi_set_version,
        )
        if actual != expected:
            raise ValueError("authorized gaze context does not match observation context")
        if not isinstance(self.geometry_snapshots, list):
            raise TypeError("geometry_snapshots must be an array")
        if not isinstance(self.events, list):
            raise TypeError("events must be an array")
        if not isinstance(self.gaze_available, bool):
            raise TypeError("gaze_available must be a boolean")
        if self.gaze_available:
            if self.viewport_width_px is None or self.viewport_height_px is None:
                raise ValueError(
                    "viewport dimensions are required for available gaze processing"
                )
        elif self.gaze_missingness is None:
            raise ValueError("gaze_missingness is required when gaze is unavailable")


@dataclass(frozen=True)
class AuthorizedGazeResult:
    """Outputs produced by the P3 handler after successful processing."""

    feature_record: dict[str, Any]
    gaze_records: list[dict[str, Any]]
    association: dict[str, Any] | None


def process_authorized_gaze(
    provider_samples: list[dict[str, Any]],
    *,
    context: AuthorizedGazeContext,
    repository: TelemetryRepository,
) -> AuthorizedGazeResult:
    """Process one trusted study/trial observation through existing P3 paths.

    The feature computation runs before durable writes, so malformed samples or
    invalid processing context do not create partial gaze rows. Association and
    FeatureRecord persistence remain separate repository transactions because
    the existing repository methods expose separate transaction boundaries;
    callers must use the existing retry/conflict behavior when a later write
    fails.
    """

    context.validate()
    if not isinstance(provider_samples, list):
        raise TypeError("provider_samples must be an array")
    if not isinstance(repository, TelemetryRepository) and not all(
        hasattr(repository, method)
        for method in ("persist_gaze_association", "persist_feature_record")
    ):
        raise TypeError("repository must provide P3 persistence methods")
    if not context.gaze_available and provider_samples:
        raise ValueError("provider_samples must be empty when gaze is unavailable")

    normalized: list[dict[str, Any]] = []
    association: dict[str, Any] | None = None
    if context.gaze_available and provider_samples:
        normalized = ProviderSampleAdapter().normalize_batch(
            provider_samples,
            session_id=context.session_id,
            viewport_width_px=context.viewport_width_px,
            viewport_height_px=context.viewport_height_px,
            calibration_status=context.calibration_status,
        )
        association = {
            "schema_version": "1.0.0",
            "association_id": (
                f"assoc-{context.session_id}-{context.study_id}-{context.trial_id}"
            ),
            "session_id": context.session_id,
            "study_id": context.study_id,
            "trial_id": context.trial_id,
            "aoi_set_version": context.aoi_set_version,
            "window_start": context.observation_context.window_start,
            "window_end": context.observation_context.window_end,
            "gaze_records": normalized,
        }
        validate_observation_association(association)

    feature_record = process_trial_gaze(
        provider_samples,
        experience_id=context.experience_id,
        session_id=context.session_id,
        study_id=context.study_id,
        trial_id=context.trial_id,
        aoi_set_version=context.aoi_set_version,
        observation_context=context.observation_context,
        geometry_snapshots=context.geometry_snapshots,
        events=context.events,
        start_event=context.start_event,
        requested_aoi_id=context.requested_aoi_id,
        viewport_width_px=context.viewport_width_px,
        viewport_height_px=context.viewport_height_px,
        gaze_available=context.gaze_available,
        gaze_missingness=context.gaze_missingness,
        calibration_status=context.calibration_status,
        feature_set_version=context.feature_set_version,
        config_version=context.config_version,
        survey_completion_ratio=context.survey_completion_ratio,
    )

    if association is not None:
        repository.persist_gaze_association(association)
    repository.persist_feature_record(feature_record)
    return AuthorizedGazeResult(feature_record, normalized, association)
