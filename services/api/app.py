import os

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from services.control_plane.router import participant_router, router as control_plane_router
from services.telemetry.persistence import IdentityConflict, TelemetryRepository

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
        allow_headers=["Accept", "Content-Type", "X-CSRF-Token"],
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


_repository: TelemetryRepository | None = None


def get_repository() -> TelemetryRepository:
    global _repository
    if _repository is None:
        _repository = TelemetryRepository.from_env()
    return _repository


@app.get("/health", response_model=HealthResponse, tags=["operations"])
def health() -> HealthResponse:
    return HealthResponse()


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(request, exc: RequestValidationError) -> JSONResponse:
    error_code = "invalid_event" if request.url.path == "/v1/events" else "invalid_request"
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
