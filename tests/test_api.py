import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

import services.api.app as api
from services.telemetry.persistence import IngestionResult


class FakeRepository:
    def __init__(self):
        self.events = {}

    def ingest(self, event):
        key = (event["session_id"], event["event_id"])
        if key in self.events:
            existing = self.events[key]
            if existing["payload"] != event["payload"]:
                from services.telemetry.persistence import IdentityConflict

                raise IdentityConflict("conflict")
            return IngestionResult(event["event_id"], True, datetime(2026, 1, 1, tzinfo=UTC))
        self.events[key] = event
        return IngestionResult(event["event_id"], False, datetime(2026, 1, 1, tzinfo=UTC))


def setup_function():
    api._repository = FakeRepository()


def test_health():
    response = api.health()
    assert response.model_dump() == {"status": "ok", "contract_version": "1.0.0"}


def test_event_endpoint_returns_frozen_acceptance_response():
    e = {
        "schema_version": "1.0.0",
        "event_id": "evt-test-1",
        "experience_id": "exp-test",
        "study_ids": ["study-test"],
        "session_id": "session-test",
        "event_type": "interaction.click",
        "occurred_at": "2026-01-01T10:00:00Z",
        "payload": {"target": "button"},
    }
    response = api.ingest_event(api.EventEnvelope.model_validate(e))
    assert response.status_code == 202
    assert json.loads(response.body) == {
        "schema_version": "1.0.0",
        "event_id": "evt-test-1",
        "status": "accepted",
        "duplicate": False,
        "ingested_at": "2026-01-01T00:00:00Z",
    }


def test_exact_retry_returns_duplicate_response():
    e = {
        "schema_version": "1.0.0",
        "event_id": "evt-test-1",
        "experience_id": "exp-test",
        "study_ids": ["study-test"],
        "session_id": "session-test",
        "event_type": "interaction.click",
        "occurred_at": "2026-01-01T10:00:00Z",
        "payload": {"target": "button"},
    }
    assert api.ingest_event(api.EventEnvelope.model_validate(e)).status_code == 202
    retry = api.ingest_event(api.EventEnvelope.model_validate(e))
    assert retry.status_code == 200
    assert json.loads(retry.body)["duplicate"] is True


def test_unknown_version_rejected():
    e = {
        "schema_version": "9.0.0",
        "event_id": "evt-test-2",
        "experience_id": "exp-test",
        "study_ids": [],
        "session_id": "session-test",
        "event_type": "interaction.click",
        "occurred_at": "2026-01-01T10:00:00Z",
        "payload": {},
    }
    with pytest.raises(ValidationError):
        api.EventEnvelope.model_validate(e)
