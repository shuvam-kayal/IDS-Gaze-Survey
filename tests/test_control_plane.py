from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import jsonschema
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

import services.api.app as api
from services.control_plane import auth
from services.control_plane.router import get_control_repository
from services.control_plane.store import ControlPlaneRepository
from services.telemetry.persistence import Base


class MemoryControlRepository:
    def __init__(self):
        self.experiences = {}
        self.audit = []
        self.studies = {}
        self.assignments = {}

    @staticmethod
    def _now():
        return datetime.now(UTC)

    def list_experiences(self):
        return list(self.experiences.values())

    def get_experience(self, experience_id):
        return self.experiences.get(experience_id)

    def create_experience(self, *, name, allowed_origins, actor_id, actor_role):
        now = self._now()
        experience_id = str(uuid4())
        record = {
            "experience_id": experience_id,
            "name": name,
            "allowed_origins": allowed_origins,
            "status": "draft",
            "config_version": None,
            "created_by": actor_id,
            "updated_by": actor_id,
            "created_at": now,
            "updated_at": now,
            "published_at": None,
            "archived_at": None,
        }
        self.experiences[experience_id] = record
        self._audit(actor_id, actor_role, "experience.created", experience_id, {"status": "draft"})
        return record

    def update_experience(self, experience_id, *, name, allowed_origins, actor_id, actor_role):
        record = self.experiences.get(experience_id)
        if not record or record["status"] != "draft":
            return None
        record.update(name=name, allowed_origins=allowed_origins, updated_by=actor_id, updated_at=self._now())
        self._audit(actor_id, actor_role, "experience.updated", experience_id, {"name": name})
        return record

    def set_lifecycle(self, experience_id, *, target_status, actor_id, actor_role):
        record = self.experiences.get(experience_id)
        if not record:
            return None
        now = self._now()
        record.update(status=target_status, updated_by=actor_id, updated_at=now)
        if target_status == "published":
            record["published_at"] = now
            record["config_version"] = f"experience-config-v1:{uuid4()}"
        if target_status == "archived":
            record["archived_at"] = now
        self._audit(actor_id, actor_role, f"experience.{target_status}", experience_id, {"status": target_status})
        return record

    def is_origin_authorized(self, experience_id, origin):
        record = self.get_experience(experience_id)
        return bool(record and record["status"] == "published" and origin in record["allowed_origins"])

    def list_audit_events(self, *, target_id=None):
        return [event for event in self.audit if target_id is None or event["target_id"] == target_id]

    def list_studies(self, experience_id):
        return [s for s in self.studies.values() if s["experience_id"] == experience_id]

    def get_study(self, study_id):
        return self.studies.get(study_id)

    def save_study(self, study_id, *, experience_id, name, priority, eligibility_rules, config, actor_id, actor_role):
        now = self._now()
        if study_id:
            record = self.studies[study_id]
            record.update(name=name, priority=priority, eligibility_rules=eligibility_rules, config=config, updated_at=now)
        else:
            study_id = str(uuid4())
            record = {"study_id": study_id, "experience_id": experience_id, "name": name,
                      "status": "draft", "priority": priority, "eligibility_rules": eligibility_rules,
                      "config_version": None, "config": config, "created_by": actor_id,
                      "updated_by": actor_id, "created_at": now, "updated_at": now,
                      "published_at": None, "archived_at": None}
            self.studies[study_id] = record
        self._audit(actor_id, actor_role, "study.created" if record["status"] == "draft" else "study.updated", study_id, {})
        return record

    def publish_study(self, study_id, *, actor_id, actor_role):
        record = self.studies[study_id]
        record["status"] = "published"
        record["config_version"] = f"study-config-v1:{uuid4()}"
        aoi_version, question_version = f"aoi-config-v1:{uuid4()}", f"question-config-v1:{uuid4()}"
        record["config"] = {**record["config"], "schema_version": "1.0.0", "config_version": record["config_version"],
                             "study_id": study_id, "experience_id": record["experience_id"],
                             "status": "active", "aoi_set_version": aoi_version, "question_set_version": question_version,
                             "survey_policy": record["config"].get("survey_policy", {"timing": "after_exposure", "consolidation": "deduplicate_by_question_id"}),
                             "gaze_required": False, "priority": record["priority"],
                             "aoi_config": {"schema_version": "1.0.0", "config_version": aoi_version, "items": record["config"].get("aois", [])},
                             "question_config": {"schema_version": "1.0.0", "config_version": question_version, "items": record["config"].get("questions", [])}}
        record["published_at"] = self._now()
        return record

    def archive_study(self, study_id, *, actor_id, actor_role):
        record = self.studies.get(study_id)
        if record: record.update(status="archived", archived_at=self._now())
        return record

    def assign_studies(self, experience_id, session_id, attributes, strategy):
        if session_id in self.assignments:
            return self.assignments[session_id]
        from services.control_plane.store import evaluate_eligibility
        eligible = [s for s in self.list_studies(experience_id) if s["status"] == "published" and evaluate_eligibility(s["eligibility_rules"], attributes)]
        eligible.sort(key=lambda s: (-s["priority"], s["study_id"]))
        chosen = eligible[:1] if strategy == "prioritized" else eligible
        self.assignments[session_id] = [{"study_id": s["study_id"], "config_version": s["config_version"], "study_config": s["config"]} for s in chosen]
        return self.assignments[session_id]

    def get_assignment(self, session_id):
        if session_id not in self.assignments: return None
        first = next(s for s in self.studies.values() if s["study_id"] == self.assignments[session_id][0]["study_id"])
        return {"session_id": session_id, "experience_id": first["experience_id"], "assignments": self.assignments[session_id], "assigned_at": self._now()}

    def _audit(self, actor_id, actor_role, action, target_id, details):
        self.audit.append(
            {
                "audit_id": str(uuid4()),
                "actor_id": actor_id,
                "actor_role": actor_role,
                "action": action,
                "target_type": "experience",
                "target_id": target_id,
                "occurred_at": self._now(),
                "details": details,
            }
        )


@pytest.fixture
def control_client(monkeypatch):
    password_hash = auth.hash_password("A-long-test-password-123")
    users = [
        {"username": "researcher", "user_id": "user-r-1", "display_name": "Researcher One", "role": "researcher", "password_hash": password_hash},
        {"username": "analyst", "user_id": "user-a-1", "display_name": "Analyst One", "role": "analyst", "password_hash": password_hash},
        {"username": "viewer", "user_id": "user-v-1", "display_name": "Viewer One", "role": "viewer", "password_hash": password_hash},
        {"username": "admin", "user_id": "user-admin", "display_name": "Admin", "role": "admin", "password_hash": password_hash},
    ]
    monkeypatch.setenv("CONTROL_PLANE_USERS_JSON", json.dumps(users))
    monkeypatch.setenv("CONTROL_PLANE_SECRET", "test-only-signing-secret-with-32-bytes-minimum")
    monkeypatch.setenv("CONTROL_PLANE_COOKIE_SECURE", "false")
    repository = MemoryControlRepository()
    api.app.dependency_overrides[get_control_repository] = lambda: repository
    with TestClient(api.app) as client:
        yield client, repository
    api.app.dependency_overrides.clear()


def sign_in(client, username):
    response = client.post(
        "/v1/control/auth/session",
        json={"username": username, "password": "A-long-test-password-123"},
    )
    assert response.status_code == 200
    return response.json()


def csrf(session):
    return {"X-CSRF-Token": session["csrf_token"]}


def test_server_role_permission_matrix_is_explicit_and_least_privilege():
    assert auth.ROLE_PERMISSIONS[auth.Role.ADMIN] == auth.ALL_PERMISSIONS
    assert auth.ROLE_PERMISSIONS[auth.Role.RESEARCHER] == {
        auth.Permission.VIEW_EXPERIENCES,
        auth.Permission.MANAGE_EXPERIENCES,
        auth.Permission.VIEW_STUDIES,
        auth.Permission.CREATE_STUDIES,
        auth.Permission.EDIT_STUDIES,
        auth.Permission.PUBLISH_STUDIES,
        auth.Permission.ARCHIVE_STUDIES,
    }
    assert auth.ROLE_PERMISSIONS[auth.Role.ANALYST] == {
        auth.Permission.VIEW_EXPERIENCES,
        auth.Permission.VIEW_STUDIES,
        auth.Permission.EXPORT_RESULTS,
    }
    assert auth.ROLE_PERMISSIONS[auth.Role.VIEWER] == {
        auth.Permission.VIEW_EXPERIENCES,
        auth.Permission.VIEW_STUDIES,
    }


def test_authentication_and_server_side_route_authorization(control_client):
    client, repository = control_client
    assert client.get("/v1/control/experiences").status_code == 401
    assert client.post("/v1/control/auth/session", json={"username": "researcher", "password": "incorrect"}).status_code == 401

    analyst = sign_in(client, "analyst")
    denied = client.post(
        "/v1/control/experiences",
        headers=csrf(analyst),
        json={"name": "Not allowed", "allowed_origins": ["https://study.example"]},
    )
    assert denied.status_code == 403
    assert repository.experiences == {}

    viewer = sign_in(client, "viewer")
    assert client.get("/v1/control/experiences").status_code == 200
    assert client.post(
        "/v1/control/experiences",
        headers=csrf(viewer),
        json={"name": "Not allowed", "allowed_origins": ["https://study.example"]},
    ).status_code == 403
    assert client.post(
        "/v1/control/experiences",
        headers={"X-CSRF-Token": "wrong"},
        json={"name": "No CSRF", "allowed_origins": ["https://study.example"]},
    ).status_code == 403


def test_experience_registry_rejects_malformed_origins_and_audits_mutations(control_client):
    client, repository = control_client
    session = sign_in(client, "researcher")
    headers = csrf(session)
    for origin in ["https://example.org/path", "https://user:pass@example.org", "https://example.org?x=1", "http://example.org", "*", "not a url"]:
        response = client.post(
            "/v1/control/experiences",
            headers=headers,
            json={"name": "Invalid origin", "allowed_origins": [origin]},
        )
        assert response.status_code == 422, origin

    created = client.post(
        "/v1/control/experiences",
        headers=headers,
        json={"name": "Study website", "allowed_origins": ["https://EXAMPLE.org:443/"]},
    )
    assert created.status_code == 201
    experience = created.json()
    assert UUID(experience["experience_id"])
    assert experience["allowed_origins"] == ["https://example.org"]
    audit = repository.list_audit_events(target_id=experience["experience_id"])
    assert len(audit) == 1
    assert audit[0]["actor_id"] == session["user_id"]
    assert audit[0]["action"] == "experience.created"
    assert audit[0]["target_id"] == experience["experience_id"]
    assert audit[0]["occurred_at"].tzinfo is not None

    update = client.put(
        f"/v1/control/experiences/{experience['experience_id']}",
        headers=headers,
        json={"name": "Updated site", "allowed_origins": ["https://new.example.org"]},
    )
    assert update.status_code == 200
    assert [event["action"] for event in repository.list_audit_events()] == [
        "experience.created", "experience.updated"
    ]


def test_published_experience_checks_browser_origin_and_cannot_be_edited(control_client):
    client, repository = control_client
    session = sign_in(client, "researcher")
    headers = csrf(session)
    experience = client.post(
        "/v1/control/experiences",
        headers=headers,
        json={"name": "Published", "allowed_origins": ["https://study.example"]},
    ).json()
    experience_id = experience["experience_id"]

    # A client-supplied body origin cannot stand in for the browser's protected Origin header.
    spoof = client.post(
        f"/v1/control/experiences/{experience_id}/authorize-origin",
        headers={"Origin": "https://attacker.example"},
        json={"origin": "https://study.example"},
    )
    assert spoof.status_code == 403
    assert client.post(
        f"/v1/control/experiences/{experience_id}/authorize-origin",
        headers={"Origin": "https://study.example"},
    ).status_code == 403  # Drafts never run with participants.

    published = client.post(
        f"/v1/control/experiences/{experience_id}/publish", headers=headers
    )
    assert published.status_code == 200
    assert published.json()["status"] == "published"
    authorized = client.post(
        f"/v1/control/experiences/{experience_id}/authorize-origin",
        headers={"Origin": "https://study.example"},
    )
    assert authorized.status_code == 200
    assert authorized.json() == {"experience_id": experience_id, "authorized": True}
    assert authorized.headers["access-control-allow-origin"] == "https://study.example"
    assert client.put(
        f"/v1/control/experiences/{experience_id}",
        headers=headers,
        json={"name": "Mutated live site", "allowed_origins": ["https://attacker.example"]},
    ).status_code == 409
    assert client.post(
        f"/v1/control/experiences/{experience_id}/archive", headers=headers
    ).status_code == 200
    assert client.post(
        f"/v1/control/experiences/{experience_id}/authorize-origin",
        headers={"Origin": "https://study.example"},
    ).status_code == 403
    audit = repository.list_audit_events(target_id=experience_id)
    assert [event["action"] for event in audit] == [
        "experience.created", "experience.published", "experience.archived"
    ]
    assert all(event["actor_id"] == session["user_id"] for event in audit)
    assert all(event["occurred_at"].tzinfo is not None for event in audit)


def test_audit_endpoint_is_admin_only_and_reports_privileged_actions(control_client):
    client, _ = control_client
    researcher = sign_in(client, "researcher")
    created = client.post(
        "/v1/control/experiences",
        headers=csrf(researcher),
        json={"name": "Audit site", "allowed_origins": ["https://audit.example"]},
    ).json()
    assert client.get("/v1/control/audit").status_code == 403
    admin = sign_in(client, "admin")
    records = client.get(f"/v1/control/audit?target_id={created['experience_id']}").json()
    assert len(records) == 1
    assert records[0]["actor_id"] == researcher["user_id"]
    assert records[0]["action"] == "experience.created"
    assert records[0]["target_type"] == "experience"
    assert records[0]["target_id"] == created["experience_id"]
    assert records[0]["occurred_at"].endswith("Z")
    assert client.get("/v1/control/roles").status_code == 200


def test_session_cookies_and_logout_require_the_signed_session_csrf_token(control_client):
    client, _ = control_client
    response = client.post(
        "/v1/control/auth/session",
        json={"username": "researcher", "password": "A-long-test-password-123"},
    )
    assert response.status_code == 200
    cookie_header = response.headers["set-cookie"].lower()
    assert "ids_researcher_session=" in cookie_header
    assert "httponly" in cookie_header
    assert "samesite=strict" in cookie_header
    assert "ids_researcher_csrf=" in cookie_header
    session = response.json()
    assert client.get("/v1/control/auth/session").json()["user_id"] == session["user_id"]
    assert client.delete("/v1/control/auth/session").status_code == 403
    assert client.delete("/v1/control/auth/session", headers=csrf(session)).status_code == 204
    assert client.get("/v1/control/auth/session").status_code == 401


def _published_experience(client, headers, name="Multi-study experience"):
    experience = client.post("/v1/control/experiences", headers=headers,
        json={"name": name, "allowed_origins": ["https://study.example"]}).json()
    assert client.post(f"/v1/control/experiences/{experience['experience_id']}/publish", headers=headers).status_code == 200
    return experience


def _study_body(experience_id, name, priority, eligibility, marker):
    return {"experience_id": experience_id, "name": name, "priority": priority,
        "eligibility_rules": eligibility, "timing_rules": {"duration_ms": marker},
        "aois": [{"aoi_id": f"aoi-{marker}", "name": f"Area {marker}", "selector": f"#area-{marker}"}],
        "questions": [{"question_id": f"q-{marker}", "prompt": f"Question {marker}", "version": "1", "type": "single_choice", "required": True, "choices": ["yes", "no"]}]}


def test_experience_can_host_independent_studies_and_pins_each_published_config(control_client):
    client, _ = control_client
    session = sign_in(client, "researcher")
    headers = csrf(session)
    experience = _published_experience(client, headers)
    exp_id = experience["experience_id"]
    first = client.post(f"/v1/control/experiences/{exp_id}/studies", headers=headers,
        json=_study_body(exp_id, "Adults", 10, {"field": "age", "op": "gte", "value": 18}, 1))
    second = client.post(f"/v1/control/experiences/{exp_id}/studies", headers=headers,
        json=_study_body(exp_id, "All visitors", 1, {"all": []}, 2))
    assert first.status_code == second.status_code == 201
    first, second = first.json(), second.json()
    assert first["study_id"] != second["study_id"]
    assert client.post(f"/v1/control/studies/{first['study_id']}/publish", headers=headers).status_code == 200
    assert client.post(f"/v1/control/studies/{second['study_id']}/publish", headers=headers).status_code == 200
    pinned = client.get(f"/v1/control/experiences/{exp_id}/studies").json()["studies"]
    assert len(pinned) == 2
    pinned_first = next(s for s in pinned if s["study_id"] == first["study_id"])
    pinned_second = next(s for s in pinned if s["study_id"] == second["study_id"])
    assert pinned_first["config"]["timing_rules"] == {"duration_ms": 1}
    assert pinned_second["config"]["timing_rules"] == {"duration_ms": 2}
    assert pinned_first["config"]["schema_version"] == "1.0.0"
    assert pinned_first["config"]["aoi_config"]["config_version"].startswith("aoi-config-v1:")
    assert pinned_first["config"]["question_config"]["config_version"].startswith("question-config-v1:")
    assert client.put(f"/v1/control/studies/{first['study_id']}", headers=headers,
        json=_study_body(exp_id, "Mutated live", 1, {"all": []}, 99)).status_code == 409


def test_assignment_is_deterministic_excludes_drafts_and_is_idempotent(control_client):
    client, _ = control_client
    session = sign_in(client, "researcher")
    headers = csrf(session)
    experience = _published_experience(client, headers)
    exp_id = experience["experience_id"]
    eligible_rule = {"all": [{"field": "age", "op": "gte", "value": 18}, {"field": "country", "op": "in", "value": ["CA", "US"]}]}
    created = []
    for name, priority, rule, marker in [("First", 5, eligible_rule, 1), ("Second", 5, eligible_rule, 2), ("Draft", 100, {"all": []}, 3)]:
        response = client.post(f"/v1/control/experiences/{exp_id}/studies", headers=headers,
            json=_study_body(exp_id, name, priority, rule, marker))
        assert response.status_code == 201
        created.append(response.json())
    for item in created[:2]:
        assert client.post(f"/v1/control/studies/{item['study_id']}/publish", headers=headers).status_code == 200
    req = {"session_id": "session-abc", "attributes": {"age": 21, "country": "CA"}, "strategy": "eligible_all"}
    a = client.post(f"/v1/control/experiences/{exp_id}/assign", headers={"Origin": "https://study.example"}, json=req)
    b = client.post(f"/v1/control/experiences/{exp_id}/assign", headers={"Origin": "https://study.example"}, json={**req, "attributes": {"age": 10}})
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json()
    assert len(a.json()["assignments"]) == 2
    assert all(item["study_id"] != created[2]["study_id"] for item in a.json()["assignments"])
    priority = client.post(f"/v1/control/experiences/{exp_id}/assign", headers={"Origin": "https://study.example"},
        json={"session_id": "session-priority", "attributes": {"age": 21, "country": "CA"}, "strategy": "prioritized"})
    assert len(priority.json()["assignments"]) == 1
    first_study_id = min(item["study_id"] for item in created[:2])
    assert priority.json()["assignments"][0]["study_id"] == first_study_id


def test_study_contract_rejects_unsafe_rules_and_invalid_question_or_aoi_config(control_client):
    client, _ = control_client
    session = sign_in(client, "researcher")
    headers = csrf(session)
    exp_id = _published_experience(client, headers)["experience_id"]
    invalids = [
        {"eligibility_rules": {"expression": "__import__('os')"}},
        {"questions": [{"question_id": "q", "prompt": "Q", "version": "1", "type": "free_text"}]},
        {"aois": [{"aoi_id": "a", "name": "A", "selector": "#a", "script": "alert(1)"}]},
    ]
    for override in invalids:
        body = _study_body(exp_id, "Invalid", 1, {"all": []}, 1)
        body.update(override)
        assert client.post(f"/v1/control/experiences/{exp_id}/studies", headers=headers, json=body).status_code == 422


def test_database_repository_persists_immutable_session_config_snapshots():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    repository = ControlPlaneRepository(engine)
    experience = repository.create_experience(name="Persistent", allowed_origins=["https://study.example"], actor_id="researcher", actor_role="researcher")
    repository.set_lifecycle(experience["experience_id"], target_status="published", actor_id="researcher", actor_role="researcher")
    draft = repository.save_study(None, experience_id=experience["experience_id"], name="Pinned", priority=3,
        eligibility_rules={"all": []}, config={"schema_version": "1.0.0", "timing_rules": {"duration_ms": 10}, "aois": [], "questions": []}, actor_id="researcher", actor_role="researcher")
    published = repository.publish_study(draft["study_id"], actor_id="researcher", actor_role="researcher")
    assignment = repository.assign_studies(experience["experience_id"], "stable-session", {}, "eligible_all")
    assert assignment[0]["config_version"] == published["config_version"]
    assert assignment[0]["study_config"] == published["config"]
    assert len(published["config_version"]) <= 80
    assert repository.assign_studies(experience["experience_id"], "stable-session", {"later": True}, "eligible_all") == assignment
    with pytest.raises(ValueError, match="Only existing draft Studies"):
        repository.save_study(draft["study_id"], experience_id=experience["experience_id"], name="mutated", priority=0,
            eligibility_rules={"all": []}, config={}, actor_id="researcher", actor_role="researcher")


def test_participant_session_bootstrap_and_pinned_resources_match_contracts(control_client):
    client, _ = control_client
    session = sign_in(client, "researcher")
    headers = csrf(session)
    experience = _published_experience(client, headers)
    exp_id = experience["experience_id"]
    study_response = client.post(f"/v1/control/experiences/{exp_id}/studies", headers=headers,
        json=_study_body(exp_id, "Participant study", 3, {"all": []}, 8))
    assert study_response.status_code == 201
    study = client.post(f"/v1/control/studies/{study_response.json()['study_id']}/publish", headers=headers).json()

    unsupported = client.post("/v1/sessions/bootstrap", headers={"Origin": "https://study.example"},
        json={"experience_id": exp_id, "schema_version": "2.0.0"})
    assert unsupported.status_code == 406
    bootstrap_response = client.post("/v1/sessions/bootstrap", headers={"Origin": "https://study.example"},
        json={"experience_id": exp_id, "attributes": {}, "camera_capture_supported": True})
    assert bootstrap_response.status_code == 200
    bootstrap = bootstrap_response.json()
    schemas = Path(__file__).parents[1] / "contracts" / "schemas"
    bootstrap_schema = json.loads((schemas / "session-bootstrap.v1.schema.json").read_text())
    jsonschema.Draft202012Validator(bootstrap_schema, format_checker=jsonschema.FormatChecker()).validate(bootstrap)
    assert set(bootstrap).isdisjoint({"user_id", "username", "role", "permissions", "actor_id", "password_hash"})
    pinned = bootstrap["eligible_studies"][0]
    config_response = client.get(f"/v1/sessions/{bootstrap['session_id']}/studies/{study['study_id']}/study-config",
        params={"config_version": pinned["config_version"]}, headers={"Origin": "https://study.example"})
    config = config_response.json()
    jsonschema.Draft202012Validator(json.loads((schemas / "study-config.v1.schema.json").read_text())).validate(config)
    aoi = client.get(f"/v1/sessions/{bootstrap['session_id']}/studies/{study['study_id']}/aoi-config",
        params={"config_version": pinned["aoi_set_version"]}, headers={"Origin": "https://study.example"}).json()
    jsonschema.Draft202012Validator(json.loads((schemas / "aoi-config.v1.schema.json").read_text())).validate(aoi)
    questions = client.get(f"/v1/sessions/{bootstrap['session_id']}/studies/{study['study_id']}/question-config",
        params={"config_version": pinned["question_set_version"]}, headers={"Origin": "https://study.example"}).json()
    jsonschema.Draft202012Validator(json.loads((schemas / "question-config.v1.schema.json").read_text())).validate(questions)
    plan = client.get(f"/v1/sessions/{bootstrap['session_id']}/survey-plan", headers={"Origin": "https://study.example"}).json()
    jsonschema.Draft202012Validator(json.loads((schemas / "survey-plan.v1.schema.json").read_text())).validate(plan)
    detail = client.get(f"/v1/sessions/{bootstrap['session_id']}/survey-plan-details", headers={"Origin": "https://study.example"}).json()
    assert detail["timing_rules"][0]["timing"] == "after_exposure"
    assert detail["questions"][0]["origins"][0]["study_id"] == study["study_id"]
    assert "created_by" not in config and "updated_by" not in config


def test_survey_consolidation_is_deterministic_and_only_merges_matching_semantics():
    from services.control_plane.survey_consolidation import consolidate_survey

    def assignment(study_id, version, prompt, timing="after_exposure"):
        return {"study_id": study_id, "config_version": f"cfg-{study_id}", "study_config": {
            "question_set_version": version,
            "survey_policy": {"timing": timing, "consolidation": "deduplicate_by_question_id"},
            "timing_rules": {"delay_ms": 5},
            "question_config": {"config_version": version, "items": [
                {"question_id": "q-shared", "prompt": prompt, "answer_type": "single_choice", "required": True,
                 "order": 0, "options": [{"option_id": "yes", "label": "Yes"}]}]}}}

    studies = [assignment("study-a", "qv-1", "Same meaning"), assignment("study-b", "qv-2", "Same meaning", "after_each_trial"), assignment("study-c", "qv-3", "Different meaning")]
    result = consolidate_survey("session-x", studies)
    assert result == consolidate_survey("session-x", studies)
    plan = result["survey_plan"]
    assert plan["study_ids"] == ["study-a", "study-b", "study-c"]
    assert plan["question_ids"][0] == "q-shared"
    assert len(plan["question_ids"]) == 2
    assert plan["question_ids"][1].startswith("q-shared@")
    origins = result["details"]["question_origins"]
    assert [origin["study_id"] for origin in origins["q-shared"]] == ["study-a", "study-b"]
    assert result["details"]["timing_rules"][1]["timing"] == "after_each_trial"
