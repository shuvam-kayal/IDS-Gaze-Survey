import os

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from services.control_plane.router import participant_router, router as control_plane_router
from services.feature_engine.authorized_gaze import process_authorized_gaze
from services.feature_engine.context_provider import TrustedContextUnavailable
from services.telemetry.persistence import (
    IdentityConflict,
    RecordIdentityConflict,
    TelemetryRepository,
)

app = FastAPI(
    title="Attention Analytics API",
    version="0.1.0",
    description="Contract-first scaffold; not production-ready.",
)

_cors_origins = sorted(
    {
        origin.strip()
        for setting in (os.getenv("CORS_ORIGINS", ""), os.getenv("CONTROL_PLANE_CORS_ORIGINS", ""))
        for origin in setting.split(",")
        if origin.strip()
    }
)
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", "Idempotency-Key", "X-CSRF-Token"],
    )

app.include_router(control_plane_router)
app.include_router(participant_router)


class HealthResponse(BaseModel):
    status: str = "ok"
    contract_version: str = "1.0.0"


class EventEnvelope(BaseModel):
    schema_version: str = Field(pattern=r"^1\.0\.0$")
    event_id: str
    experience_id: str
    study_ids: list[str]
    session_id: str
    participant_id: str | None = None
    event_type: str
    occurred_at: str
    payload: dict


class GazeObservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(pattern=r"^1\.0\.0$")
    request_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    provider_samples: list[dict] = Field(max_length=250)


class GazeObservationResponse(BaseModel):
    schema_version: str = "1.0.0"
    request_id: str
    status: str
    duplicate: bool
    feature_record_id: str
    sample_count: int


_repository: TelemetryRepository | None = None
_gaze_context_provider = None


def get_repository() -> TelemetryRepository:
    global _repository
    if _repository is None:
        _repository = TelemetryRepository.from_env()
    return _repository


def get_gaze_context_provider():
    """Return the server-owned context provider, failing closed when absent."""
    if _gaze_context_provider is None:
        raise TrustedContextUnavailable(
            "server-side gaze context authorization is not configured"
        )
    return _gaze_context_provider


@app.get("/health", response_model=HealthResponse, tags=["operations"])
def health() -> HealthResponse:
    return HealthResponse()


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(request, exc: RequestValidationError) -> JSONResponse:
    if request.url.path == "/v1/gaze/observations":
        error_code = "invalid_gaze_observation"
    elif request.url.path == "/v1/events":
        error_code = "invalid_event"
    else:
        error_code = "invalid_request"
    return JSONResponse(
        status_code=422,
        content={
            "schema_version": "1.0.0",
            "error": {"code": error_code, "message": str(exc.errors())},
        },
    )


@app.post("/v1/events", tags=["telemetry"])
def ingest_event(event: EventEnvelope) -> JSONResponse:
    """Persist one validated EventEnvelope with frozen retry semantics."""
    try:
        result = get_repository().ingest(event.model_dump())
    except IdentityConflict:
        return JSONResponse(
            status_code=409,
            content={
                "schema_version": "1.0.0",
                "error": {
                    "code": "event_identity_conflict",
                    "message": "event_id is already used with different content",
                },
            },
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content={
                "schema_version": "1.0.0",
                "error": {"code": "invalid_event", "message": str(exc)},
            },
        )

    return JSONResponse(
        status_code=200 if result.duplicate else 202,
        content={
            "schema_version": "1.0.0",
            "event_id": result.event_id,
            "status": "duplicate" if result.duplicate else "accepted",
            "duplicate": result.duplicate,
            "ingested_at": result.ingested_at.isoformat().replace("+00:00", "Z"),
        },
    )


@app.post("/v1/gaze/observations", tags=["gaze"])
def ingest_gaze_observation(request: GazeObservationRequest) -> JSONResponse:
    """Process one complete, bounded observation through the P3 pipeline.

    The context provider is deliberately server-owned. The default deployment
    has no provider and therefore rejects the request instead of trusting the
    browser to authorize its own session or study context. Tests may inject an
    explicit provider by assigning the private module variable.
    """
    try:
        context = get_gaze_context_provider().resolve(request.model_dump())
        if context.session_id != request.session_id:
            raise ValueError("trusted gaze context does not match request session")
        result = process_authorized_gaze(
            request.provider_samples,
            context=context,
            repository=get_repository(),
        )
    except TrustedContextUnavailable:
        return JSONResponse(
            status_code=503,
            content={
                "schema_version": "1.0.0",
                "error": {
                    "code": "gaze_context_unavailable",
                    "message": "server-side gaze context authorization is unavailable",
                },
            },
        )
    except RecordIdentityConflict:
        return JSONResponse(
            status_code=409,
            content={
                "schema_version": "1.0.0",
                "error": {
                    "code": "gaze_identity_conflict",
                    "message": "gaze observation identity is already used with different content",
                },
            },
        )
    except (TypeError, ValueError) as exc:
        return JSONResponse(
            status_code=422,
            content={
                "schema_version": "1.0.0",
                "error": {"code": "invalid_gaze_observation", "message": str(exc)},
            },
        )

    response = GazeObservationResponse(
        request_id=request.request_id,
        status="duplicate" if result.duplicate else "processed",
        duplicate=result.duplicate,
        feature_record_id=result.feature_record["feature_record_id"],
        sample_count=len(result.gaze_records),
    )
    return JSONResponse(
        status_code=200 if result.duplicate else 202,
        content=response.model_dump(),
    )
