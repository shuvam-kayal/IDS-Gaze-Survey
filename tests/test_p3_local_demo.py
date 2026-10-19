import importlib
from datetime import timedelta

import pytest

import services.api.app as api


class DemoRepository:
    def __init__(self):
        self.associations = {}
        self.features = {}

    def persist_gaze_association(self, association):
        key = (association["association_id"], association["session_id"])
        self.associations[key] = association
        return association["gaze_records"]

    def persist_feature_record(self, record):
        self.features[record["feature_record_id"]] = record
        return record

    def gaze_association_exists(self, association_id, session_id):
        return (association_id, session_id) in self.associations

    def feature_record_exists(self, feature_record_id):
        return feature_record_id in self.features


@pytest.fixture
def demo(monkeypatch):
    monkeypatch.setenv("P3_LOCAL_DEMO", "1")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    module = importlib.import_module("scripts.p3_local_demo")
    repository = DemoRepository()
    monkeypatch.setattr(module, "_base_repository", repository)
    monkeypatch.setattr(module, "_failure_repository", None)
    api._repository = repository
    api._gaze_context_provider = module.DemoContextProvider()
    yield module, repository
    api._repository = None
    api._gaze_context_provider = None


def _request(module, request_id, samples):
    start = module.DEMO_START
    provider_samples = [
        {
            "schema_version": "1.0.0",
            "provider": "synthetic-provider",
            "provider_version": "demo-test-1",
            "sample_id": f"demo-test-{offset}",
            "capture_time_ms": offset,
            "occurred_at": (start + timedelta(seconds=1, milliseconds=offset)).isoformat().replace(
                "+00:00", "Z"
            ),
            "x_px": 25,
            "y_px": 25,
            "valid": True,
            "quality": {"confidence": 0.9, "flags": []},
        }
        for offset in (0, 100, 200)
    ] if samples else []
    return api.GazeObservationRequest(
        schema_version="1.0.0",
        request_id=request_id,
        session_id=module.SESSION_ID,
        provider_samples=provider_samples,
    )


def test_clean_normal_retry_and_camera_denied_fallback(demo):
    module, repository = demo
    first = module._demo_ingest(_request(module, "normal-test", True))
    retry = module._demo_ingest(_request(module, "retry-test", True))
    denied = module._demo_ingest(_request(module, "camera-denied-test", False))

    assert first.status_code == 202
    assert retry.status_code == 200
    assert denied.status_code == 202
    assert len(repository.associations) == 1
    assert len(repository.features) == 2
    assert any(record["modality"] == "non_gaze_only" for record in repository.features.values())


def test_persistence_failure_is_controlled_and_retry_recovers(demo):
    module, repository = demo
    first = module._demo_ingest(_request(module, "persistence-failure-test", True))
    recovery = module._demo_ingest(_request(module, "persistence-failure-test", True))

    assert first.status_code == 500
    assert b"demo_persistence_failure" in first.body
    assert recovery.status_code == 202
    assert len(repository.associations) == 1
    assert len(repository.features) == 1
