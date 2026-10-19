"""Trusted-context interface for the additive M4 gaze transport."""

from __future__ import annotations

from typing import Any, Protocol

from services.feature_engine.authorized_gaze import AuthorizedGazeContext


class TrustedContextUnavailable(ValueError):
    """The server cannot establish authorized P1/P2 context for a request."""


class TrustedGazeContextProvider(Protocol):
    """Resolve request hints using server-owned authorization and state.

    Implementations must not treat browser-provided IDs, consent flags or
    configuration values as proof. A production implementation belongs to the
    API/integrator with P1/P2 inputs. Tests may inject an explicit double.
    """

    def resolve(self, request: dict[str, Any]) -> AuthorizedGazeContext: ...
