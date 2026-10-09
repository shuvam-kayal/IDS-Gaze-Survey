from fastapi.testclient import TestClient

from services.api.app import app

client = TestClient(app)


def test_health():
    r = client.get('/health')
    assert r.status_code == 200
    assert r.json() == {'status': 'ok', 'contract_version': '1.0.0'}


def test_event_endpoint_does_not_claim_persistence():
    e = {'schema_version':'1.0.0','event_id':'evt-test-1','experience_id':'exp-test','study_ids':['study-test'],'session_id':'session-test','event_type':'interaction.click','occurred_at':'2026-01-01T10:00:00Z','payload':{'target':'button'}}
    r = client.post('/v1/events', json=e)
    assert r.status_code == 202
    assert r.json() == {'accepted': True, 'event_id': 'evt-test-1', 'persisted': False}


def test_unknown_version_rejected():
    e = {'schema_version':'9.0.0','event_id':'evt-test-2','experience_id':'exp-test','study_ids':[],'session_id':'session-test','event_type':'interaction.click','occurred_at':'2026-01-01T10:00:00Z','payload':{}}
    assert client.post('/v1/events', json=e).status_code == 422
