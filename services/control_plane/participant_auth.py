"""Server-side participant-session credential verification.

This module authenticates possession of an opaque session credential. It does
not identify a participant in the real-world and is intentionally not wired to
consent or gaze routes until those contracts are approved.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from services.control_plane.store import ControlPlaneRepository

PARTICIPANT_SESSION_COOKIE = "ids_participant_session"


def require_participant_session(
    session_id: str,
    credential: str | None,
    repository: ControlPlaneRepository,
) -> dict:
    """Require a live cookie credential bound to exactly ``session_id``."""
    if not credential:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Participant session authentication required")
    session = repository.verify_participant_session(session_id=session_id, credential=credential)
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired participant session")
    return session
