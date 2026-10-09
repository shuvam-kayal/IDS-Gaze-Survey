"""Provider-neutral gaze adapter boundary. No external estimator is bundled yet."""
from typing import Any, Protocol

class GazeProviderAdapter(Protocol):
    def normalize(self, provider_sample: dict[str, Any], *, session_id: str) -> dict[str, Any]: ...

class NotConfiguredGazeAdapter:
    def normalize(self, provider_sample: dict[str, Any], *, session_id: str) -> dict[str, Any]:
        raise NotImplementedError("Configure an approved provider and implement canonical GazeRecord normalization.")
