"""Local-only mock-backed browser workflow for the P3 integration boundary.

This module is deliberately a development launcher, not production API wiring.
It binds only to localhost, requires P3_LOCAL_DEMO=1, uses a fixture-derived
trusted context, and exposes report/reset routes for one dedicated demo session.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.routing import APIRoute

import services.api.app as api
from services.feature_engine.authorized_gaze import AuthorizedGazeContext
from services.feature_engine.context_provider import TrustedContextUnavailable
from services.gaze_engine.context import TrialObservationContext
from services.telemetry.persistence import TelemetryRepository

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "packages" / "gaze-provider-webgazer" / "smoke-test" / "p3-demo.html"
BUNDLE = ROOT / "packages" / "gaze-provider-webgazer" / "smoke-test" / "dist" / "p3-demo.js"
SESSION_ID = os.environ.get("P3_DEMO_SESSION_ID", "local-p3-demo-session")
STUDY_ID = "study-product-evaluation"
TRIAL_ID = "trial-study-product-0001"
AOI_VERSION = "1.0.0"
EXPERIENCE_ID = "exp-demo-store"
DEMO_START = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=10)
DEMO_END = DEMO_START + timedelta(minutes=10)


def _load_example(name: str) -> dict[str, Any]:
    return json.loads((ROOT / "contracts" / "examples" / name).read_text(encoding="utf-8"))


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _context(*, gaze_available: bool = True, missingness: str | None = None) -> AuthorizedGazeContext:
    bootstrap = _load_example("session-bootstrap.json")
    bootstrap["session_id"] = SESSION_ID
    bootstrap["eligible_studies"][0]["study_id"] = STUDY_ID
    bootstrap["eligible_studies"][0]["aoi_set_version"] = AOI_VERSION
    aoi_config = _load_example("aoi-config.json")
    aoi_config["study_id"] = STUDY_ID
    aoi_config["aoi_set_version"] = AOI_VERSION
    if bootstrap["eligible_studies"][0]["aoi_set_version"] != aoi_config["aoi_set_version"]:
        raise RuntimeError("demo fixture AOI version mismatch")
    geometry = _load_example("geometry-snapshot-v2.json")
    geometry.update(
        {
            "snapshot_id": "geometry-local-p3-demo",
            "session_id": SESSION_ID,
            "study_id": STUDY_ID,
            "captured_at": _iso(DEMO_START - timedelta(seconds=1)),
            "aoi_set_version": AOI_VERSION,
            "viewport_width_px": 100,
            "viewport_height_px": 100,
            "rectangles": [
                {
                    "aoi_id": "headline",
                    "left_px": 0,
                    "top_px": 0,
                    "right_px": 80,
                    "bottom_px": 80,
                    "priority": 10,
                }
            ],
        }
    )
    start = _load_example("trial-exposure-start.json")
    start.update(
        {
            "event_id": "evt-local-p3-demo-start",
            "session_id": SESSION_ID,
            "study_ids": [STUDY_ID],
            "occurred_at": _iso(DEMO_START),
            "payload": {"trial_id": TRIAL_ID},
        }
    )
    observation = TrialObservationContext(
        SESSION_ID, STUDY_ID, TRIAL_ID, AOI_VERSION, _iso(DEMO_START), _iso(DEMO_END)
    )
    return AuthorizedGazeContext(
        experience_id=EXPERIENCE_ID,
        session_id=SESSION_ID,
        study_id=STUDY_ID,
        trial_id=TRIAL_ID,
        aoi_set_version=AOI_VERSION,
        observation_context=observation,
        geometry_snapshots=[geometry],
        events=[start],
        start_event=start if gaze_available else None,
        requested_aoi_id="headline",
        viewport_width_px=100,
        viewport_height_px=100,
        gaze_available=gaze_available,
        gaze_missingness=missingness,
    )


class DemoContextProvider:
    """Explicit test-only trusted context provider for this localhost demo."""

    def resolve(self, request: dict[str, Any]) -> AuthorizedGazeContext:
        request_id = request.get("request_id", "")
        if request_id.startswith("missing-context-"):
            raise TrustedContextUnavailable("demo missing trusted context")
        if request_id.startswith("context-mismatch-"):
            mismatched = _context()
            return AuthorizedGazeContext(
                **{**mismatched.__dict__, "session_id": f"{SESSION_ID}-other"}
            )
        if request_id.startswith("camera-denied-"):
            return _context(gaze_available=False, missingness="gaze.permission_denied")
        return _context()


class FailOnceRepository:
    """Test-only wrapper that fails one FeatureRecord write, then recovers."""

    def __init__(self, wrapped: TelemetryRepository) -> None:
        self.wrapped = wrapped
        self.fail_next_feature = True

    def persist_feature_record(self, record: dict[str, Any]) -> dict[str, Any]:
        if self.fail_next_feature:
            self.fail_next_feature = False
            raise RuntimeError("demo injected FeatureRecord persistence failure")
        return self.wrapped.persist_feature_record(record)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.wrapped, name)


if os.environ.get("P3_LOCAL_DEMO") != "1":
    raise RuntimeError("Set P3_LOCAL_DEMO=1 to enable the isolated localhost demo")

# Reuse the repository's documented test connection when a developer has not
# separately set DATABASE_URL; production configuration still requires the
# normal DATABASE_URL variable.
if not os.environ.get("DATABASE_URL") and os.environ.get("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

api._repository = TelemetryRepository.from_env()
api._gaze_context_provider = DemoContextProvider()
_base_repository = api._repository
_failure_repository: FailOnceRepository | None = None


@api.app.get("/", include_in_schema=False)
def demo_page() -> FileResponse:
    return FileResponse(PAGE)


@api.app.get("/p3-demo.js", include_in_schema=False)
def demo_bundle() -> FileResponse:
    if not BUNDLE.exists():
        raise HTTPException(404, "Build the P3 demo bundle first")
    return FileResponse(BUNDLE, media_type="text/javascript")


@api.app.get("/__p3_demo/config", include_in_schema=False)
def demo_config() -> dict[str, Any]:
    bootstrap = _load_example("session-bootstrap.json")
    bootstrap["session_id"] = SESSION_ID
    aoi_config = _load_example("aoi-config.json")
    aoi_config["aoi_set_version"] = AOI_VERSION
    return {
        "session_id": SESSION_ID,
        "study_id": STUDY_ID,
        "trial_id": TRIAL_ID,
        "aoi_set_version": AOI_VERSION,
        "window_start": _iso(DEMO_START),
        "window_end": _iso(DEMO_END),
        "viewport_width_px": 100,
        "viewport_height_px": 100,
        "fixture_sources": [
            "contracts/examples/session-bootstrap.json",
            "contracts/examples/aoi-config.json",
            "contracts/examples/geometry-snapshot-v2.json",
            "contracts/examples/trial-exposure-start.json",
        ],
        "session_bootstrap": bootstrap,
        "aoi_config": aoi_config,
    }


@api.app.get("/__p3_demo/report", include_in_schema=False)
def demo_report() -> dict[str, Any]:
    return {
        "session_id": SESSION_ID,
        "gaze_records": _base_repository.list_gaze_records(SESSION_ID),
        "feature_records": _base_repository.list_feature_records(SESSION_ID),
    }


@api.app.post("/__p3_demo/reset", include_in_schema=False)
def demo_reset() -> dict[str, Any]:
    deleted = _base_repository.delete_session(SESSION_ID)
    if _failure_repository is not None:
        _failure_repository.fail_next_feature = True
    return {"session_id": SESSION_ID, "deleted": deleted}


def _select_repository(request_id: str) -> None:
    global _failure_repository
    if request_id.startswith("persistence-failure-"):
        if _failure_repository is None:
            _failure_repository = FailOnceRepository(_base_repository)
        api._repository = _failure_repository
    else:
        api._repository = _base_repository


_original_ingest = api.ingest_gaze_observation


def _demo_ingest(request: api.GazeObservationRequest):
    _select_repository(request.request_id)
    return _original_ingest(request)


for _route in api.app.router.routes:
    if isinstance(_route, APIRoute) and _route.path == "/v1/gaze/observations":
        _route.endpoint = _demo_ingest
        _route.dependant.call = _demo_ingest
        break


if __name__ == "__main__":
    uvicorn.run(api.app, host="127.0.0.1", port=int(os.environ.get("P3_DEMO_PORT", "8000")))
