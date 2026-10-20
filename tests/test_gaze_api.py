import json

from test_authorized_gaze import FakeRepository, context, sample

import services.api.app as api


class FakeContextProvider:
    def __init__(self, resolved_context):
        self.resolved_context = resolved_context

    def resolve(self, request):
        return self.resolved_context


def request(samples):
    return api.GazeObservationRequest(
        schema_version="1.0.0",
        request_id="gaze-request-1",
        session_id="session-authorized-1",
        provider_samples=samples,
    )


def setup_function():
    api._repository = FakeRepository()
    api._gaze_context_provider = FakeContextProvider(context())


def teardown_function():
    api._repository = None
    api._gaze_context_provider = None


def test_gaze_route_is_fail_closed_without_server_context_provider():
    api._gaze_context_provider = None
    response = api.ingest_gaze_observation(request([]))
    assert response.status_code == 503
    assert json.loads(response.body)["error"]["code"] == "gaze_context_unavailable"


def test_gaze_route_processes_and_retries_complete_observation():
    payload = [sample("sample-0", 0), sample("sample-1", 100), sample("sample-2", 200)]
    first = api.ingest_gaze_observation(request(payload))
    retry = api.ingest_gaze_observation(request(list(reversed(payload))))

    assert first.status_code == 202
    assert json.loads(first.body)["duplicate"] is False
    assert retry.status_code == 200
    assert json.loads(retry.body)["duplicate"] is True


def test_gaze_route_rejects_invalid_provider_sample_without_persistence():
    response = api.ingest_gaze_observation(request([sample("bad", 0, x=101)]))
    assert response.status_code == 422
    assert json.loads(response.body)["error"]["code"] == "invalid_gaze_observation"
    assert not api._repository.associations
    assert not api._repository.features


def test_gaze_route_rejects_context_for_another_session():
    mismatched = api.GazeObservationRequest(
        schema_version="1.0.0",
        request_id="gaze-request-2",
        session_id="session-other",
        provider_samples=[],
    )
    response = api.ingest_gaze_observation(mismatched)
    assert response.status_code == 422
    assert "does not match request session" in json.loads(response.body)["error"]["message"]
