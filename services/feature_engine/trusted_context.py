"""Server-owned resolution of the authorized P3 gaze-processing context."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from services.feature_engine.authorized_gaze import AuthorizedGazeContext
from services.gaze_engine.adapter import GazeNormalizationError, ProviderSampleAdapter
from services.gaze_engine.context import utc_timestamp
from services.gaze_engine.geometry import GeometryScope, validate_geometry_snapshot
from services.gaze_engine.geometry_bridge import SERVER_VALIDATED_PROVENANCE
from services.gaze_engine.lifecycle import (
    START_EVENT_TYPE,
    resolve_authorized_trial_lifecycle,
)

AUTHORIZED_REQUEST_VERSION = "1.1.0"


class TrustedGazeContextProvider:
    """Resolve one additive authorized request from verified server state.

    The API boundary must authenticate the participant cookie first and pass
    only the resulting session record here. Raw credentials never enter this
    class or gaze-processing code.
    """

    def __init__(self, *, control_repository: Any, telemetry_repository: Any, participant_session: dict[str, Any]):
        self.control_repository = control_repository
        self.telemetry_repository = telemetry_repository
        self.participant_session = participant_session

    @staticmethod
    def _request(request: dict[str, Any]) -> tuple[str, str, str, list[dict[str, Any]]]:
        required = {"schema_version", "request_id", "session_id", "study_id", "trial_id", "provider_samples"}
        if not isinstance(request, dict) or set(request) != required:
            raise GazeNormalizationError("authorized gaze request has invalid fields")
        if request["schema_version"] != AUTHORIZED_REQUEST_VERSION:
            raise GazeNormalizationError("unsupported authorized gaze request version")
        for field in ("request_id", "session_id", "study_id", "trial_id"):
            if not isinstance(request[field], str) or not request[field]:
                raise GazeNormalizationError(f"authorized gaze request {field} is invalid")
        if not isinstance(request["provider_samples"], list) or len(request["provider_samples"]) > 250:
            raise GazeNormalizationError("authorized gaze provider_samples must be a bounded array")
        return request["session_id"], request["study_id"], request["trial_id"], request["provider_samples"]

    def _assignment(self, session_id: str, study_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        assignment = self.control_repository.get_assignment(session_id)
        if not isinstance(assignment, dict) or assignment.get("session_id") != session_id or assignment.get("experience_id") != self.participant_session.get("experience_id"):
            raise GazeNormalizationError("participant assignment is unavailable or mismatched")
        matches = [item for item in assignment.get("assignments", []) if isinstance(item, dict) and item.get("study_id") == study_id]
        if len(matches) != 1:
            raise GazeNormalizationError("study is not unambiguously assigned to participant session")
        selected = matches[0]
        config = selected.get("study_config")
        if not isinstance(config, dict):
            raise GazeNormalizationError("assigned study configuration is invalid")
        aoi_set_version = config.get("aoi_set_version")
        aoi_config = config.get("aoi_config")
        if not isinstance(aoi_set_version, str) or not aoi_set_version or not isinstance(aoi_config, dict) or aoi_config.get("config_version") != aoi_set_version:
            raise GazeNormalizationError("assigned AOI configuration is not pinned")
        return assignment, selected

    def _consent(self, session_id: str) -> None:
        state = self.control_repository.participant_consent_state(session_id)
        decisions = {item.get("scope"): item.get("decision") for item in (state or {}).get("consent", [])}
        if decisions.get("research_participation") != "accepted":
            raise GazeNormalizationError("research participation consent is required")
        if decisions.get("camera_gaze") != "accepted":
            raise GazeNormalizationError("camera/gaze consent is required")

    def resolve(self, request: dict[str, Any]) -> AuthorizedGazeContext:
        session_id, study_id, trial_id, provider_samples = self._request(request)
        session = self.participant_session
        if not isinstance(session, dict) or session.get("session_id") != session_id:
            raise GazeNormalizationError("authorized gaze request session does not match authenticated session")
        if session.get("status") != "open" or session.get("withdrawn_at") is not None:
            raise GazeNormalizationError("participant session is not open")
        expires_at = session.get("expires_at")
        expiry = expires_at if isinstance(expires_at, datetime) else utc_timestamp(expires_at, "participant session expires_at")
        now = datetime.now(UTC)
        if expiry.tzinfo is None or expiry.utcoffset() != UTC.utcoffset(None) or expiry <= now:
            raise GazeNormalizationError("participant session is expired")
        self._consent(session_id)
        assignment, selected = self._assignment(session_id, study_id)
        config = selected["study_config"]
        aoi_set_version = config["aoi_set_version"]
        observation_context, reason = resolve_authorized_trial_lifecycle(
            self.telemetry_repository,
            participant_session=session,
            study_assignment=assignment,
            study_id=study_id,
            trial_id=trial_id,
            aoi_set_version=aoi_set_version,
            now=now,
        )
        if observation_context is None:
            raise GazeNormalizationError(reason or "trial observation window is unavailable")
        events = self.telemetry_repository.list_events(session_id, study_id=study_id)
        start_events = [event for event in events if event.get("event_type") == START_EVENT_TYPE and event.get("payload", {}).get("trial_id") == trial_id]
        if len(start_events) != 1:
            raise GazeNormalizationError("trial start event is not unambiguous")

        snapshots = self.telemetry_repository.list_geometry_snapshots(
            session_id,
            study_id=study_id,
            aoi_set_version=aoi_set_version,
            at=observation_context.end,
            provenance=SERVER_VALIDATED_PROVENANCE,
        )
        snapshots = [
            snapshot for snapshot in snapshots
            if observation_context.start <= utc_timestamp(snapshot["captured_at"], "geometry captured_at") < observation_context.end
        ]
        if not snapshots:
            raise GazeNormalizationError("no server-validated geometry is available for the trial window")
        scope = GeometryScope(session_id, study_id, aoi_set_version)
        for snapshot in snapshots:
            validate_geometry_snapshot(snapshot, scope=scope)
        latest = snapshots[-1]
        normalized_samples = ProviderSampleAdapter().normalize_batch(
            provider_samples,
            session_id=session_id,
            viewport_width_px=latest["viewport_width_px"],
            viewport_height_px=latest["viewport_height_px"],
            calibration_status="not_required",
        )
        for record in normalized_samples:
            occurred_at = utc_timestamp(record["occurred_at"], "gaze_record.occurred_at")
            if not observation_context.start <= occurred_at < observation_context.end:
                raise GazeNormalizationError("provider sample is outside the trusted observation window")

        context = AuthorizedGazeContext(
            experience_id=session["experience_id"], session_id=session_id, study_id=study_id,
            trial_id=trial_id, aoi_set_version=aoi_set_version,
            observation_context=observation_context, geometry_snapshots=snapshots,
            events=events, start_event=start_events[0], requested_aoi_id=None,
            viewport_width_px=latest["viewport_width_px"], viewport_height_px=latest["viewport_height_px"],
            gaze_available=True, calibration_status="not_required",
            config_version=selected.get("config_version"),
        )
        context.validate()
        return context
