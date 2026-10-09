"""P3-owned ingestion boundary; persistence is intentionally not claimed yet."""
from typing import Any

def validate_event_shape(event: dict[str, Any]) -> bool:
    required = {"schema_version", "event_id", "experience_id", "study_ids", "session_id", "event_type", "occurred_at", "payload"}
    return required.issubset(event) and event.get("schema_version") == "1.0.0" and isinstance(event.get("payload"), dict)
