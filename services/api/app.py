from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="Attention Analytics API", version="0.1.0", description="Contract-first scaffold; not production-ready.")

class HealthResponse(BaseModel):
    status: str = "ok"
    contract_version: str = "1.0.0"

class EventEnvelope(BaseModel):
    schema_version: str = Field(pattern=r"^1\.0\.0$")
    event_id: str
    experience_id: str
    study_ids: list[str] = Field(default_factory=list)
    session_id: str
    participant_id: str | None = None
    event_type: str
    occurred_at: str
    payload: dict

@app.get("/health", response_model=HealthResponse, tags=["operations"])
def health() -> HealthResponse:
    return HealthResponse()

@app.post("/v1/events", status_code=202, tags=["telemetry"])
def ingest_event(event: EventEnvelope) -> dict[str, object]:
    """Validate shape only. No durable persistence is implemented yet."""
    return {"accepted": True, "event_id": event.event_id, "persisted": False}
