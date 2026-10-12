"""P3-owned event validation and batch-level idempotency helpers.

Durable persistence is intentionally not claimed yet. Deduplication is limited
to one session and one input batch because the frozen EventEnvelope contract
does not define a cross-session event identity scope.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any


EVENT_SCHEMA_VERSION = "1.0.0"
REQUIRED_EVENT_FIELDS = {
    "schema_version",
    "event_id",
    "experience_id",
    "study_ids",
    "session_id",
    "event_type",
    "occurred_at",
    "payload",
}


def _parse_utc_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("occurred_at must be a non-empty RFC 3339 timestamp")
    if len(value) < 11 or value[10] != "T":
        raise ValueError("occurred_at must be a valid RFC 3339 timestamp")

    try:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("occurred_at must be a valid RFC 3339 timestamp") from exc

    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError("occurred_at must include a UTC offset")
    return parsed


def validate_event(event: dict[str, Any]) -> None:
    """Validate the currently approved EventEnvelope representation.

    Raises ``ValueError`` with deterministic messages. This is deliberately a
    local contract check and does not persist or mutate the event.
    """

    if not isinstance(event, dict):
        raise ValueError("event must be an object")

    missing = sorted(REQUIRED_EVENT_FIELDS - event.keys())
    if missing:
        raise ValueError(f"event is missing required fields: {', '.join(missing)}")
    if event["schema_version"] != EVENT_SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version: {event['schema_version']!r}")

    for field in ("event_id", "experience_id", "session_id", "event_type"):
        if not isinstance(event[field], str) or not event[field]:
            raise ValueError(f"{field} must be a non-empty string")

    study_ids = event["study_ids"]
    if not isinstance(study_ids, list) or any(
        not isinstance(study_id, str) for study_id in study_ids
    ):
        raise ValueError("study_ids must be an array of strings")
    if len(study_ids) != len(set(study_ids)):
        raise ValueError("study_ids must contain unique values")
    if not isinstance(event["payload"], dict):
        raise ValueError("payload must be an object")

    _parse_utc_timestamp(event["occurred_at"])


def validate_event_shape(event: dict[str, Any]) -> bool:
    """Backward-compatible boolean wrapper around :func:`validate_event`."""

    try:
        validate_event(event)
    except ValueError:
        return False
    return True


def deduplicate_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate and deduplicate events within each session and input batch.

    Identical retries are retained once. Reusing an event ID for different
    payloads in the same session is rejected because silently choosing one
    would make derived features non-deterministic. Events from different
    sessions are not merged because the frozen contract does not authorize
    cross-session deduplication.
    """

    unique: dict[tuple[str, str], dict[str, Any]] = {}
    fingerprints: dict[tuple[str, str], str] = {}
    for event in events:
        validate_event(event)
        key = (event["session_id"], event["event_id"])
        fingerprint = json.dumps(event, sort_keys=True, separators=(",", ":"))
        if key in fingerprints:
            if fingerprints[key] != fingerprint:
                raise ValueError(
                    "conflicting duplicate event_id within session: "
                    f"{event['event_id']!r}"
                )
            continue
        fingerprints[key] = fingerprint
        unique[key] = event

    return sorted(
        unique.values(),
        key=lambda event: (
            _parse_utc_timestamp(event["occurred_at"]),
            event["session_id"],
            event["event_id"],
        ),
    )
