"""Reusable, deterministic gaze metrics built from Slice U outputs."""

from __future__ import annotations

import json
from hashlib import sha256
from itertools import pairwise
from math import log2
from typing import Any

from services.feature_engine.non_gaze import build_non_gaze_features
from services.gaze_engine.adapter import GazeNormalizationError
from services.gaze_engine.context import TrialObservationContext
from services.gaze_engine.fixation import FIXATION_ALGORITHM_VERSION, AOIAssignment, Fixation
from services.telemetry.ingestion import _parse_utc_timestamp

METRIC_ALGORITHM_VERSION = FIXATION_ALGORITHM_VERSION
START_EVENT_TYPE = "trial.exposure_started"
UNAVAILABLE_START = "gaze.observation_start_missing"
NO_QUALIFYING_FIXATION = "gaze.no_qualifying_fixation"
METRIC_UNDEFINED = "gaze.metric_undefined"
NO_SAMPLES = "gaze.no_samples"
NO_QUALIFYING_OBSERVATIONS = "gaze.no_qualifying_observations"
AMBIGUOUS_START = "gaze.observation_start_ambiguous"


def _timestamp(value: Any, field: str):
    try:
        return _parse_utc_timestamp(value)
    except (TypeError, ValueError) as exc:
        raise GazeNormalizationError(f"{field} must be a valid UTC timestamp") from exc


def _metric(
    value: Any,
    *,
    unit: str,
    missingness: str | None,
    aoi_set_version: str,
    time_window: str,
    requested_aoi_id: str | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
) -> dict[str, Any]:
    return {
        "value": value,
        "unit": unit,
        "missingness": missingness,
        "time_window": time_window,
        "aoi_set_version": aoi_set_version,
        "feature_algorithm_version": METRIC_ALGORITHM_VERSION,
        "requested_aoi_id": requested_aoi_id,
        "window_start": window_start,
        "window_end": window_end,
    }


def _validate_start_event(event: dict[str, Any], *, session_id: str, study_id: str) -> str:
    if not isinstance(event, dict):
        raise GazeNormalizationError("start_event must be an object")
    required = {
        "schema_version",
        "event_id",
        "experience_id",
        "study_ids",
        "session_id",
        "event_type",
        "occurred_at",
        "payload",
    }
    if not required.issubset(event):
        raise GazeNormalizationError("start_event is missing required fields")
    if event["schema_version"] != "1.0.0" or event["event_type"] != START_EVENT_TYPE:
        raise GazeNormalizationError("unsupported trial exposure start event")
    if event["session_id"] != session_id or event["study_ids"] != [study_id]:
        raise GazeNormalizationError("start_event study/session context does not match metrics")
    if not isinstance(event["payload"], dict) or not isinstance(event["payload"].get("trial_id"), str):
        raise GazeNormalizationError("start_event payload requires trial_id")
    _timestamp(event["occurred_at"], "start_event.occurred_at")
    return event["payload"]["trial_id"]


def resolve_start_event(
    start_events: list[dict[str, Any]], *, session_id: str, study_id: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Resolve retries and repeated starts for one study-scoped trial input.

    Exact duplicate event identities collapse to one event. Reusing an event ID
    with a different canonical payload raises. Distinct valid starts are
    ambiguous and return ``(None, gaze.observation_start_ambiguous)`` so TTFF
    cannot silently choose a timestamp.
    """

    by_id: dict[str, tuple[str, dict[str, Any]]] = {}
    for event in start_events:
        trial_id = _validate_start_event(event, session_id=session_id, study_id=study_id)
        canonical = json.dumps(event, sort_keys=True, separators=(",", ":"))
        event_id = event["event_id"]
        if event_id in by_id and by_id[event_id][0] != canonical:
            raise GazeNormalizationError("conflicting duplicate trial exposure start event")
        by_id[event_id] = (canonical, event)
        if trial_id != _validate_start_event(next(iter(by_id.values()))[1], session_id=session_id, study_id=study_id):
            raise GazeNormalizationError("start events must identify one trial")
    unique = [entry[1] for entry in sorted(by_id.values(), key=lambda entry: entry[0])]
    if not unique:
        return None, UNAVAILABLE_START
    if len(unique) > 1:
        return None, AMBIGUOUS_START
    return unique[0], None


def _ordered_pairs(
    fixations: list[Fixation], assignments: list[AOIAssignment], context: TrialObservationContext | None = None
) -> list[tuple[Fixation, AOIAssignment]]:
    by_id = {fixation.fixation_id: fixation for fixation in fixations}
    if len(by_id) != len(fixations) or len({assignment.observation_id for assignment in assignments}) != len(assignments):
        raise GazeNormalizationError("fixation and AOI identities must be unique")
    if set(by_id) != {assignment.observation_id for assignment in assignments}:
        raise GazeNormalizationError("fixation and AOI assignments must match")
    if context is not None:
        for fixation, assignment in ((by_id[item.observation_id], item) for item in assignments):
            if (fixation.session_id, fixation.study_id, fixation.trial_id, fixation.aoi_set_version) != (
                context.session_id, context.study_id, context.trial_id, context.aoi_set_version
            ):
                raise GazeNormalizationError("fixation context does not match requested observation context")
            if assignment.session_id is not None and (
                assignment.session_id, assignment.study_id, assignment.trial_id, assignment.aoi_set_version
            ) != (context.session_id, context.study_id, context.trial_id, context.aoi_set_version):
                raise GazeNormalizationError("AOI assignment context does not match requested observation context")
    return sorted(
        ((by_id[assignment.observation_id], assignment) for assignment in assignments),
        key=lambda pair: (_timestamp(pair[0].start_at, "fixation.start_at"), pair[0].fixation_id),
    )


def _availability_reason(gaze_available: bool, gaze_missingness: str | None, has_fixations: bool) -> str | None:
    if not gaze_available:
        return gaze_missingness or NO_SAMPLES
    if not has_fixations:
        return NO_SAMPLES
    return None


def compute_gaze_metrics(
    fixations: list[Fixation],
    assignments: list[AOIAssignment],
    *,
    session_id: str,
    study_id: str,
    aoi_set_version: str,
    requested_aoi_id: str | None,
    start_event: dict[str, Any] | list[dict[str, Any]] | None,
    gaze_available: bool = True,
    gaze_missingness: str | None = None,
    time_window: str = "trial",
    window_start: str | None = None,
    window_end: str | None = None,
    observation_context: TrialObservationContext | None = None,
) -> dict[str, dict[str, Any]]:
    """Compute TTFF, dwell, revisits, transitions, entropy, and scan path.

    Dwell is the sum of fixation durations only; time between fixations is not
    attributed. A fixation is included only when it lies wholly inside the
    requested window; partially overlapping fixations are excluded rather than
    interpolated. Revisit state includes unresolved intervals. Transitions use
    consecutive resolved observations, while scan paths preserve unresolved
    observations and collapse only consecutive duplicates. Entropy is base-2
    Shannon entropy over resolved fixation dwell shares; it is null when fewer
    than two resolved observations exist and is zero for a repeated single AOI
    with at least two observations.
    """

    if observation_context is not None and (
        observation_context.session_id != session_id
        or observation_context.study_id != study_id
        or observation_context.aoi_set_version != aoi_set_version
    ):
        raise GazeNormalizationError("requested metric context does not match observation context")
    if observation_context is None and any(
        fixation.session_id is not None or fixation.study_id is not None or fixation.trial_id is not None
        for fixation in fixations
    ):
        raise GazeNormalizationError("observation_context is required for contextualized fixations")
    pairs = _ordered_pairs(fixations, assignments, observation_context)
    start_error: str | None = None
    if isinstance(start_event, list):
        start_event, start_error = resolve_start_event(
            start_event, session_id=session_id, study_id=study_id
        )
    start_time = None
    if start_event is not None:
        start_trial_id = _validate_start_event(start_event, session_id=session_id, study_id=study_id)
        if observation_context is not None and start_trial_id != observation_context.trial_id:
            raise GazeNormalizationError("start_event trial_id does not match observation context")
        start_time = _timestamp(start_event["occurred_at"], "start_event.occurred_at")
    lower_bound = observation_context.start if observation_context else (_timestamp(window_start, "window_start") if window_start else start_time)
    upper_bound = observation_context.end if observation_context else (_timestamp(window_end, "window_end") if window_end else None)
    if lower_bound is not None and upper_bound is not None and upper_bound <= lower_bound:
        raise GazeNormalizationError("window_end must be after window_start")
    if lower_bound is not None or upper_bound is not None:
        pairs = [
            (fixation, assignment)
            for fixation, assignment in pairs
            if (lower_bound is None or _timestamp(fixation.start_at, "fixation.start_at") >= lower_bound)
            and (upper_bound is None or _timestamp(fixation.end_at, "fixation.end_at") <= upper_bound)
        ]
    availability_reason = _availability_reason(gaze_available, gaze_missingness, bool(fixations))
    if observation_context is not None and gaze_available and not fixations:
        availability_reason = NO_QUALIFYING_OBSERVATIONS
    common = {
        "aoi_set_version": aoi_set_version,
        "time_window": time_window,
        "requested_aoi_id": requested_aoi_id,
        "window_start": observation_context.window_start if observation_context else (window_start or (start_event["occurred_at"] if start_event else None)),
        "window_end": observation_context.window_end if observation_context else window_end,
    }
    if availability_reason:
        ttff_reason = availability_reason
        dwell_reason = availability_reason
        revisit_reason = availability_reason
        transition_reason = availability_reason
        entropy_reason = availability_reason
        scan_reason = availability_reason
    else:
        ttff_reason = dwell_reason = revisit_reason = transition_reason = entropy_reason = scan_reason = None

    if start_error and not availability_reason:
        ttff_reason = start_error
    elif start_event is None and not availability_reason:
        ttff_reason = UNAVAILABLE_START

    resolved = [
        (fixation, assignment)
        for fixation, assignment in pairs
        if assignment.aoi_id != "aoi.unresolved"
    ]
    requested = [
        (fixation, assignment)
        for fixation, assignment in resolved
        if requested_aoi_id is not None and assignment.aoi_id == requested_aoi_id
    ]

    if start_time is not None and not availability_reason:
        after_start = [fixation for fixation, _ in requested if _timestamp(fixation.start_at, "fixation.start_at") >= start_time]
        if after_start:
            ttff_value = int((_timestamp(after_start[0].start_at, "fixation.start_at") - start_time).total_seconds() * 1000)
            ttff_reason = None
        else:
            ttff_value = None
            ttff_reason = NO_QUALIFYING_FIXATION
    else:
        ttff_value = None

    dwell_value = sum(fixation.duration_ms for fixation, _ in requested) if not dwell_reason else None

    sequence = [assignment.aoi_id for _, assignment in pairs]
    scan_path: list[str] = []
    for aoi_id in sequence:
        if not scan_path or scan_path[-1] != aoi_id:
            scan_path.append(aoi_id)
    resolved_ids = [assignment.aoi_id for _, assignment in resolved]
    transitions = [
        {"from_aoi_id": previous, "to_aoi_id": current}
        for previous, current in pairwise(resolved_ids)
        if previous != current
    ]

    revisits = 0
    seen_aois: set[str] = set()
    last_resolved: str | None = None
    left_last = False
    for aoi_id in sequence:
        if aoi_id == "aoi.unresolved":
            if last_resolved is not None:
                left_last = True
            continue
        if aoi_id != last_resolved:
            if aoi_id in seen_aois:
                revisits += 1
            seen_aois.add(aoi_id)
            last_resolved = aoi_id
            left_last = False
        elif left_last:
            revisits += 1
            left_last = False

    if entropy_reason:
        entropy_value = None
    elif len(resolved) < 2:
        entropy_value = None
        entropy_reason = METRIC_UNDEFINED
    else:
        dwell_by_aoi: dict[str, int] = {}
        for fixation, assignment in resolved:
            dwell_by_aoi[assignment.aoi_id] = dwell_by_aoi.get(assignment.aoi_id, 0) + fixation.duration_ms
        total_dwell = sum(dwell_by_aoi.values())
        entropy_value = (
            -sum((duration / total_dwell) * log2(duration / total_dwell) for duration in dwell_by_aoi.values())
            if total_dwell > 0
            else None
        )
        if entropy_value is None:
            entropy_reason = METRIC_UNDEFINED

    if not pairs and not availability_reason:
        scan_path = []
        empty_reason = NO_QUALIFYING_OBSERVATIONS if observation_context else NO_SAMPLES
        scan_reason = empty_reason
        transition_reason = empty_reason
        revisit_reason = empty_reason
        entropy_reason = empty_reason
        dwell_reason = empty_reason
        if start_time is None:
            ttff_reason = UNAVAILABLE_START
        else:
            ttff_reason = empty_reason
    elif not resolved and not availability_reason:
        entropy_reason = "aoi.unresolved"

    return {
        "gaze.ttff_ms": _metric(ttff_value, unit="ms", missingness=ttff_reason, **common),
        "gaze.dwell_time_ms": _metric(dwell_value, unit="ms", missingness=dwell_reason, **common),
        "gaze.revisit_count": _metric(
            revisits if not revisit_reason else None, unit="count", missingness=revisit_reason, **common
        ),
        "gaze.transition_count": _metric(
            len(transitions) if not transition_reason else None,
            unit="count",
            missingness=transition_reason,
            **common,
        ),
        "gaze.transitions": _metric(
            transitions if not transition_reason else None,
            unit="AOI-pairs",
            missingness=transition_reason,
            **common,
        ),
        "gaze.entropy_bits": _metric(entropy_value, unit="bits", missingness=entropy_reason, **common),
        "gaze.scan_path": _metric(scan_path if not scan_reason else None, unit="AOI-sequence", missingness=scan_reason, **common),
    }


def build_gaze_feature_record(
    events: list[dict[str, Any]],
    metrics: dict[str, dict[str, Any]],
    *,
    experience_id: str,
    study_id: str,
    session_id: str,
    aoi_set_version: str,
    feature_set_version: str = "1.0.0",
    config_version: str | None = None,
    gaze_available: bool = True,
    calibration_status: str | None = None,
    gaze_missingness_reason: str | None = None,
) -> dict[str, Any]:
    """Build a schema-shaped FeatureRecord without changing its contract."""

    feature_values = {**build_non_gaze_features(events), **metrics}
    missingness = sorted(
        {
            value["missingness"]
            for value in metrics.values()
            if value.get("missingness")
        }
    )
    if gaze_missingness_reason:
        missingness.append(gaze_missingness_reason)
    missingness = sorted(set(missingness))
    identity = json.dumps(
        {
            "experience_id": experience_id,
            "study_id": study_id,
            "session_id": session_id,
            "feature_set_version": feature_set_version,
            "aoi_set_version": aoi_set_version,
            "features": feature_values,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return {
        "schema_version": "1.0.0",
        "feature_record_id": f"feat-{sha256(identity).hexdigest()[:16]}",
        "experience_id": experience_id,
        "study_id": study_id,
        "session_id": session_id,
        "feature_set_version": feature_set_version,
        "config_version": config_version,
        "aoi_set_version": aoi_set_version,
        "modality": "gaze_and_non_gaze" if gaze_available else "non_gaze_only",
        "window": None,
        "features": feature_values,
        "quality": {
            "gaze_available": gaze_available,
            "missingness": missingness,
            "calibration_status": calibration_status,
        },
        "source_event_count": len(events),
    }
