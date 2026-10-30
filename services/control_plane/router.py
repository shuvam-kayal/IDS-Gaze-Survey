"""Authenticated researcher APIs and public, server-checked Experience origin gate."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from services.control_plane.auth import (
    ROLE_PERMISSIONS,
    SESSION_SECONDS,
    Permission,
    Principal,
    Role,
    clear_session_cookies,
    get_principal,
    hash_password,
    issue_session,
    load_credentials,
    require_csrf,
    require_permission,
    set_session_cookies,
    verify_password,
)
from services.control_plane.participant_auth import require_participant_session
from services.control_plane.store import ControlPlaneRepository
from services.control_plane.survey_consolidation import consolidate_survey
from services.feature_engine.session_processing import persist_non_gaze_feature_records
from services.gaze_engine.adapter import GazeNormalizationError
from services.gaze_engine.geometry_bridge import validate_server_geometry_submission
from services.telemetry.persistence import RecordIdentityConflict, TelemetryRepository

PARTICIPANT_SESSION_COOKIE = "ids_participant_session"


def participant_cookie_secure() -> bool:
    """Force Secure cookies outside explicitly local development modes."""
    setting = os.getenv("PARTICIPANT_COOKIE_SECURE", "").lower()
    development = os.getenv("APP_ENV", "production").lower() in {"development", "dev", "test", "local"}
    return setting in {"1", "true", "yes"} or not development

router = APIRouter(prefix="/v1/control", tags=["control-plane"])
participant_router = APIRouter(prefix="/v1", tags=["participant-configuration"])
_repository: ControlPlaneRepository | None = None
_telemetry_repository: TelemetryRepository | None = None
_DUMMY_PASSWORD_HASH = hash_password("invalid-researcher-account-password")


def get_control_repository() -> ControlPlaneRepository:
    global _repository
    if _repository is None:
        try:
            _repository = ControlPlaneRepository.from_env()
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503, detail="Experience registry storage is not configured"
            ) from exc
    return _repository


def get_telemetry_repository() -> TelemetryRepository:
    global _telemetry_repository
    if _telemetry_repository is None:
        try:
            _telemetry_repository = TelemetryRepository.from_env()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="Telemetry storage is not configured") from exc
    return _telemetry_repository


def canonicalize_origin(value: str) -> str:
    """Return an exact scheme+host+port origin, rejecting URLs with paths or credentials."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("Origin must be an absolute HTTP(S) origin")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Origin has an invalid host or port") from exc
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("Only an HTTP(S) origin without credentials, path, query, or fragment is allowed")
    try:
        host = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("Origin host is invalid") from exc
    if not host or any(char.isspace() for char in host):
        raise ValueError("Origin host is invalid")
    if parsed.scheme.lower() == "http" and host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Non-local origins must use HTTPS")
    default_port = 80 if parsed.scheme.lower() == "http" else 443
    port_text = f":{port}" if port is not None and port != default_port else ""
    host_text = f"[{host}]" if ":" in host else host
    return f"{parsed.scheme.lower()}://{host_text}{port_text}"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ParticipantConsentRequest(StrictModel):
    scope: Literal["research_participation", "camera_gaze"]
    decision: Literal["accepted", "declined"]
    policy_version: str = Field(min_length=1, max_length=255)
    occurred_at: str = Field(min_length=1, max_length=64)

    @field_validator("policy_version")
    @classmethod
    def nonblank_policy_version(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("policy_version must not be blank")
        return value.strip()


class ParticipantConsentResponse(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    scope: Literal["research_participation", "camera_gaze"]
    decision: Literal["accepted", "declined"]
    policy_version: str
    occurred_at: str
    duplicate: bool


class ParticipantWithdrawalRequest(StrictModel):
    occurred_at: str = Field(min_length=1, max_length=64)


class ParticipantWithdrawalResponse(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["withdrawn"]
    withdrawn_at: str


class SurveySubmissionRequest(StrictModel):
    submission_id: str = Field(min_length=1, max_length=255)
    session_id: str = Field(min_length=1, max_length=255)
    responses: list[dict] = Field(max_length=500)


class SurveySubmissionResponse(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    submission_id: str
    session_id: str
    responses: list[dict]
    duplicate: bool = False


class GeometrySubmissionRequest(StrictModel):
    study_id: str = Field(min_length=1, max_length=255)
    trial_id: str = Field(min_length=1, max_length=255)
    snapshot: dict


class GeometrySubmissionResponse(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    snapshot_id: str
    status: Literal["accepted", "duplicate"]
    duplicate: bool
    provenance: Literal["server_validated"]


def _participant_timestamp(value: str, field_name: str) -> datetime:
    try:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(None):
            raise ValueError
        return parsed
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{field_name} must be a valid UTC RFC 3339 timestamp") from exc


class LoginRequest(StrictModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=1024)


class ExperienceWrite(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    allowed_origins: list[str] = Field(min_length=1, max_length=25)

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Experience name cannot be blank")
        return value.strip()

    @field_validator("allowed_origins")
    @classmethod
    def canonical_origins(cls, values: list[str]) -> list[str]:
        if any(not value for value in values):
            raise ValueError("Allowed origins cannot be blank")
        canonical = [canonicalize_origin(value) for value in values]
        if len(set(canonical)) != len(canonical):
            raise ValueError("Allowed origins must be unique")
        return canonical


class UserSessionResponse(StrictModel):
    user_id: str
    username: str
    display_name: str
    role: Role
    permissions: list[Permission]
    csrf_token: str
    expires_in_seconds: int


class ExperienceResponse(StrictModel):
    experience_id: str
    name: str
    allowed_origins: list[str]
    status: str
    config_version: str | None = None
    created_by: str
    updated_by: str
    created_at: str
    updated_at: str
    published_at: str | None = None
    archived_at: str | None = None


class ExperienceListResponse(StrictModel):
    experiences: list[ExperienceResponse]


class OriginAuthorizationResponse(StrictModel):
    experience_id: str
    authorized: bool


class AuditEventResponse(StrictModel):
    audit_id: str
    actor_id: str
    actor_role: str
    action: str
    target_type: str
    target_id: str
    occurred_at: str
    details: dict


def _validate_rule(rule: object, depth: int = 0) -> None:
    if depth > 8 or not isinstance(rule, dict):
        raise ValueError("Eligibility rule must be a bounded rule object")
    if set(rule) == {"all"} or set(rule) == {"any"}:
        children = rule[next(iter(rule))]
        if not isinstance(children, list) or len(children) > 20:
            raise ValueError("Eligibility all/any groups must contain at most 20 rules")
        for child in children:
            _validate_rule(child, depth + 1)
        return
    if set(rule) == {"not"}:
        _validate_rule(rule["not"], depth + 1)
        return
    if set(rule) - {"field", "op", "value"} or not isinstance(rule.get("field"), str):
        raise ValueError("Eligibility predicate has invalid fields")
    if not rule["field"] or len(rule["field"]) > 100:
        raise ValueError("Eligibility field name is invalid")
    op = rule.get("op")
    if op not in {"eq", "ne", "in", "contains", "gte", "lte", "exists"}:
        raise ValueError("Eligibility operator is not supported")
    if op != "exists" and "value" not in rule:
        raise ValueError("Eligibility predicate requires a value")
    if op == "in" and (not isinstance(rule.get("value"), list) or len(rule["value"]) > 100):
        raise ValueError("Eligibility 'in' requires a list of at most 100 values")


class StudyWrite(StrictModel):
    experience_id: str
    name: str = Field(min_length=1, max_length=200)
    priority: int = Field(default=0, ge=0, le=100000)
    eligibility_rules: dict = Field(default_factory=lambda: {"all": []})
    timing_rules: dict = Field(default_factory=dict)
    survey_policy: dict = Field(default_factory=lambda: {"timing": "after_exposure", "consolidation": "deduplicate_by_question_id"})
    aois: list[dict] = Field(default_factory=list, max_length=500)
    questions: list[dict] = Field(default_factory=list, max_length=500)
    gaze_required: bool = False

    @field_validator("name")
    @classmethod
    def study_name_not_blank(cls, value: str) -> str:
        if not value.strip(): raise ValueError("Study name cannot be blank")
        return value.strip()

    @field_validator("eligibility_rules")
    @classmethod
    def safe_rule_set(cls, value: dict) -> dict:
        _validate_rule(value)
        return value

    @field_validator("survey_policy")
    @classmethod
    def valid_survey_policy(cls, value: dict) -> dict:
        if set(value) != {"timing", "consolidation"}:
            raise ValueError("Survey policy requires timing and consolidation")
        if value["timing"] not in {"before_exposure", "after_exposure", "after_each_trial", "batched_after_exposure"}:
            raise ValueError("Survey timing policy is unsupported")
        if value["consolidation"] not in {"deduplicate_by_question_id", "keep_study_scoped"}:
            raise ValueError("Survey consolidation policy is unsupported")
        return value

    @field_validator("aois")
    @classmethod
    def validate_aois(cls, values: list[dict]) -> list[dict]:
        ids = set()
        for item in values:
            if set(item) - {"aoi_id", "name", "label", "selector", "required", "tracking_strategy", "priority", "enabled"} or not all(isinstance(item.get(k), str) and item[k].strip() for k in ("aoi_id", "name" if "name" in item else "label", "selector")):
                raise ValueError("AOIs require aoi_id, name, and selector; unknown fields are rejected")
            if item["aoi_id"] in ids: raise ValueError("AOI identifiers must be unique")
            ids.add(item["aoi_id"])
            if len(item["aoi_id"]) > 100 or len(item.get("name", item.get("label"))) > 200 or len(item["selector"]) > 500:
                raise ValueError("AOI identifiers, names, or selectors exceed their limits")
            if "required" in item and not isinstance(item["required"], bool):
                raise ValueError("AOI required must be a boolean")
            if item.get("tracking_strategy", "css_selector") not in {"css_selector", "data_attribute", "manual_fallback"}:
                raise ValueError("AOI tracking strategy is unsupported")
            if not isinstance(item.get("priority", 0), int) or not isinstance(item.get("enabled", True), bool):
                raise ValueError("AOI priority or enabled flag is invalid")
            if not item["selector"].startswith(("#", ".", "[")) and any(c in item["selector"] for c in "{};"):
                raise ValueError("AOI selector is invalid")
        return [{"aoi_id": item["aoi_id"], "label": item.get("label", item.get("name")),
                 "selector": item["selector"], "tracking_strategy": item.get("tracking_strategy", "css_selector"),
                 "priority": item.get("priority", 0), "enabled": item.get("enabled", True)} for item in values]

    @field_validator("questions")
    @classmethod
    def validate_questions(cls, values: list[dict]) -> list[dict]:
        ids = set()
        normalized = []
        for index, item in enumerate(values):
            answer_type = item.get("answer_type", item.get("type"))
            if answer_type not in {"single_choice", "multi_choice", "multiple_choice", "free_text", "boolean", "scale", "rating"}:
                raise ValueError("Question type is unsupported")
            if not all(isinstance(item.get(k), str) and item[k].strip() for k in ("question_id", "prompt")):
                raise ValueError("Questions require question_id and prompt")
            if "version" in item and (not isinstance(item["version"], str) or not item["version"].strip()):
                raise ValueError("Question version must be a non-empty string")
            if item["question_id"] in ids: raise ValueError("Question identifiers must be unique")
            ids.add(item["question_id"])
            if len(item["question_id"]) > 100 or len(item["prompt"]) > 2000 or len(item.get("version", "1")) > 80:
                raise ValueError("Question identifiers, prompts, or versions exceed their limits")
            if "required" in item and not isinstance(item["required"], bool):
                raise ValueError("Question required must be a boolean")
            if "order" in item and (not isinstance(item["order"], int) or isinstance(item["order"], bool) or item["order"] < 0):
                raise ValueError("Question order must be a non-negative integer")
            if answer_type in {"single_choice", "multiple_choice", "multi_choice"}:
                choices = item.get("options", item.get("choices"))
                if not isinstance(choices, list) or not choices:
                    raise ValueError("Choice questions require unique, non-empty choices")
                options = []
                for option_index, choice in enumerate(choices):
                    if isinstance(choice, str): option = {"option_id": f"option-{option_index + 1}", "label": choice}
                    elif isinstance(choice, dict):
                        if set(choice) - {"option_id", "label"}: raise ValueError("Question option has unsupported fields")
                        option = {"option_id": choice.get("option_id"), "label": choice.get("label")}
                    else: raise ValueError("Question options must be strings or option objects")
                    if not all(isinstance(option[k], str) and option[k].strip() for k in ("option_id", "label")):
                        raise ValueError("Question options require non-empty IDs and labels")
                    options.append(option)
                if len({option["option_id"] for option in options}) != len(options):
                    raise ValueError("Question option IDs must be unique")
            elif answer_type == "boolean":
                choices = item.get("options", item.get("choices", [
                    {"option_id": "true", "label": "Yes"},
                    {"option_id": "false", "label": "No"},
                ]))
                if not isinstance(choices, list) or len(choices) != 2:
                    raise ValueError("Boolean questions require true and false options")
                options = []
                for choice in choices:
                    if not isinstance(choice, dict) or set(choice) - {"option_id", "label"}:
                        raise ValueError("Boolean options require true/false IDs and labels")
                    options.append({"option_id": choice.get("option_id"), "label": choice.get("label")})
                if {option.get("option_id") for option in options} != {"true", "false"} or not all(
                    isinstance(option.get("label"), str) and option["label"].strip()
                    for option in options
                ):
                    raise ValueError("Boolean options require true/false IDs and non-empty labels")
            elif answer_type == "free_text":
                if item.get("options") is not None or item.get("choices") is not None:
                    raise ValueError("Free-text questions cannot define choices")
            elif answer_type in {"rating", "scale"}:
                if not isinstance(item.get("min"), int) or not isinstance(item.get("max"), int) or item["min"] >= item["max"]:
                    raise ValueError("Rating and scale questions require min < max")
                if item["max"] - item["min"] > 100: raise ValueError("Scale range cannot exceed 100 steps")
                options = [{"option_id": str(n), "label": str(n)} for n in range(item["min"], item["max"] + 1)]
            if set(item) - {"question_id", "prompt", "version", "type", "answer_type", "required", "choices", "options", "min", "max", "labels", "order"}:
                raise ValueError("Question contains unsupported fields")
            normalized.append({"question_id": item["question_id"], "prompt": item["prompt"],
                "answer_type": "multi_choice" if answer_type == "multiple_choice" else "scale" if answer_type == "rating" else answer_type,
                "required": item.get("required", False), "order": item.get("order", index),
                **({"options": options} if answer_type in {"single_choice", "multiple_choice", "multi_choice", "rating", "scale", "boolean"} else {})})
        return sorted(normalized, key=lambda question: question["order"])


class StudyListResponse(StrictModel):
    studies: list[dict]


class AssignmentRequest(StrictModel):
    session_id: str = Field(min_length=1, max_length=255)
    attributes: dict = Field(default_factory=dict)
    strategy: str = Field(default="eligible_all", pattern="^(eligible_all|prioritized)$")


class BootstrapRequest(StrictModel):
    schema_version: str = "1.0.0"
    experience_id: str | None = None
    attributes: dict = Field(default_factory=dict)
    strategy: str = Field(default="eligible_all", pattern="^(eligible_all|prioritized)$")
    camera_capture_supported: bool = False


class SessionBootstrapResponse(StrictModel):
    schema_version: str = "1.0.0"
    session_id: str
    experience_id: str
    participant_id: str | None = None
    experience_config_version: str
    eligible_studies: list[dict]
    privacy_notice_version: str
    research_consent_version: str
    camera_capture_supported: bool
    issued_at: str
    expires_at: str


def _timestamp(value) -> str:
    # PostgreSQL returns timestamptz values in the connection's configured
    # timezone. Normalize them before serializing the contract's UTC value.
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _experience_response(record: dict) -> ExperienceResponse:
    return ExperienceResponse(
        **{
            **record,
            "created_at": _timestamp(record["created_at"]),
            "updated_at": _timestamp(record["updated_at"]),
            "published_at": _timestamp(record["published_at"]) if record.get("published_at") else None,
            "archived_at": _timestamp(record["archived_at"]) if record.get("archived_at") else None,
        }
    )


def _study_response(record: dict) -> dict:
    return {**record, "created_at": _timestamp(record["created_at"]),
            "updated_at": _timestamp(record["updated_at"]),
            "published_at": _timestamp(record["published_at"]) if record.get("published_at") else None,
            "archived_at": _timestamp(record["archived_at"]) if record.get("archived_at") else None}


def _principal_response(principal: Principal) -> UserSessionResponse:
    return UserSessionResponse(
        user_id=principal.user_id,
        username=principal.username,
        display_name=principal.display_name,
        role=principal.role,
        permissions=sorted(ROLE_PERMISSIONS[principal.role], key=lambda item: item.value),
        csrf_token=principal.csrf_token,
        expires_in_seconds=SESSION_SECONDS,
    )


@router.post("/auth/session", response_model=UserSessionResponse)
def sign_in(body: LoginRequest, response: Response) -> UserSessionResponse:
    credentials = load_credentials()
    if not credentials:
        raise HTTPException(status_code=503, detail="Researcher sign-in is not configured")
    user = credentials.get(body.username)
    encoded_hash = user.password_hash if user else _DUMMY_PASSWORD_HASH
    password_valid = verify_password(body.password, encoded_hash)
    if not user or not password_valid:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token, csrf_token, max_age = issue_session(user)
    set_session_cookies(response, token, csrf_token, max_age)
    return UserSessionResponse(
        user_id=user.user_id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        permissions=sorted(ROLE_PERMISSIONS[user.role], key=lambda item: item.value),
        csrf_token=csrf_token,
        expires_in_seconds=max_age,
    )


@router.get("/auth/session", response_model=UserSessionResponse)
def current_session(principal: Annotated[Principal, Depends(get_principal)]) -> UserSessionResponse:
    return _principal_response(principal)


@router.delete("/auth/session", status_code=204)
def sign_out(
    response: Response,
    principal: Annotated[Principal, Depends(require_csrf)],
) -> Response:
    clear_session_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/roles", response_model=dict[str, list[Permission]])
def role_permissions(
    _: Annotated[Principal, Depends(require_permission(Permission.MANAGE_USERS))],
) -> dict[str, list[Permission]]:
    return {
        role.value: sorted(permissions, key=lambda item: item.value)
        for role, permissions in ROLE_PERMISSIONS.items()
    }


@router.get("/experiences", response_model=ExperienceListResponse)
def list_experiences(
    _: Annotated[Principal, Depends(require_permission(Permission.VIEW_EXPERIENCES))],
    repository: Annotated[ControlPlaneRepository, Depends(get_control_repository)],
) -> ExperienceListResponse:
    return ExperienceListResponse(
        experiences=[_experience_response(record) for record in repository.list_experiences()]
    )


@router.post("/experiences", response_model=ExperienceResponse, status_code=201)
def create_experience(
    body: ExperienceWrite,
    principal: Annotated[Principal, Depends(require_permission(Permission.MANAGE_EXPERIENCES))],
    _: Annotated[Principal, Depends(require_csrf)],
    repository: Annotated[ControlPlaneRepository, Depends(get_control_repository)],
) -> ExperienceResponse:
    record = repository.create_experience(
        name=body.name,
        allowed_origins=body.allowed_origins,
        actor_id=principal.user_id,
        actor_role=principal.role.value,
    )
    return _experience_response(record)


@router.get("/experiences/{experience_id}", response_model=ExperienceResponse)
def get_experience(
    experience_id: str,
    _: Annotated[Principal, Depends(require_permission(Permission.VIEW_EXPERIENCES))],
    repository: Annotated[ControlPlaneRepository, Depends(get_control_repository)],
) -> ExperienceResponse:
    record = repository.get_experience(experience_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Experience not found")
    return _experience_response(record)


@router.put("/experiences/{experience_id}", response_model=ExperienceResponse)
def update_experience(
    experience_id: str,
    body: ExperienceWrite,
    principal: Annotated[Principal, Depends(require_permission(Permission.MANAGE_EXPERIENCES))],
    _: Annotated[Principal, Depends(require_csrf)],
    repository: Annotated[ControlPlaneRepository, Depends(get_control_repository)],
) -> ExperienceResponse:
    existing = repository.get_experience(experience_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Experience not found")
    if existing["status"] != "draft":
        raise HTTPException(status_code=409, detail="Only draft Experiences can be edited")
    try:
        record = repository.update_experience(
            experience_id,
            name=body.name,
            allowed_origins=body.allowed_origins,
            actor_id=principal.user_id,
            actor_role=principal.role.value,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Experience not found")
    return _experience_response(record)


@router.post("/experiences/{experience_id}/publish", response_model=ExperienceResponse)
def publish_experience(
    experience_id: str,
    principal: Annotated[Principal, Depends(require_permission(Permission.PUBLISH_STUDIES))],
    _: Annotated[Principal, Depends(require_csrf)],
    repository: Annotated[ControlPlaneRepository, Depends(get_control_repository)],
) -> ExperienceResponse:
    existing = repository.get_experience(experience_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Experience not found")
    if existing["status"] != "draft":
        raise HTTPException(status_code=409, detail="Only draft Experiences can be published")
    if not existing["allowed_origins"]:
        raise HTTPException(status_code=422, detail="At least one allowed origin is required")
    try:
        record = repository.set_lifecycle(
            experience_id,
            target_status="published",
            actor_id=principal.user_id,
            actor_role=principal.role.value,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Experience not found")
    return _experience_response(record)


@router.post("/experiences/{experience_id}/archive", response_model=ExperienceResponse)
def archive_experience(
    experience_id: str,
    principal: Annotated[Principal, Depends(require_permission(Permission.ARCHIVE_STUDIES))],
    _: Annotated[Principal, Depends(require_csrf)],
    repository: Annotated[ControlPlaneRepository, Depends(get_control_repository)],
) -> ExperienceResponse:
    existing = repository.get_experience(experience_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Experience not found")
    if existing["status"] == "archived":
        raise HTTPException(status_code=409, detail="Experience is already archived")
    try:
        record = repository.set_lifecycle(
            experience_id,
            target_status="archived",
            actor_id=principal.user_id,
            actor_role=principal.role.value,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Experience not found")
    return _experience_response(record)


@router.post(
    "/experiences/{experience_id}/authorize-origin",
    response_model=OriginAuthorizationResponse,
)
def authorize_experience_origin(
    experience_id: str,
    response: Response,
    repository: Annotated[ControlPlaneRepository, Depends(get_control_repository)],
    origin_header: Annotated[str | None, Header(alias="Origin")] = None,
) -> OriginAuthorizationResponse:
    """Public entry gate. The request's protected Origin header is the sole origin input."""
    if not origin_header:
        raise HTTPException(status_code=403, detail="A browser Origin header is required")
    try:
        origin = canonicalize_origin(origin_header)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Origin is not authorized") from exc
    if not repository.is_origin_authorized(experience_id, origin):
        raise HTTPException(status_code=403, detail="Origin is not authorized")
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Vary"] = "Origin"
    return OriginAuthorizationResponse(experience_id=experience_id, authorized=True)


@router.get("/audit", response_model=list[AuditEventResponse])
def list_audit_events(
    _: Annotated[Principal, Depends(require_permission(Permission.MANAGE_USERS))],
    repository: Annotated[ControlPlaneRepository, Depends(get_control_repository)],
    target_id: str | None = None,
) -> list[AuditEventResponse]:
    return [
        AuditEventResponse(
            **{**record, "occurred_at": _timestamp(record["occurred_at"])}
        )
        for record in repository.list_audit_events(target_id=target_id)
    ]


@router.get("/experiences/{experience_id}/studies", response_model=StudyListResponse)
def list_studies(
    experience_id: str,
    _: Annotated[Principal, Depends(require_permission(Permission.VIEW_STUDIES))],
    repository: Annotated[ControlPlaneRepository, Depends(get_control_repository)],
) -> StudyListResponse:
    if repository.get_experience(experience_id) is None:
        raise HTTPException(status_code=404, detail="Experience not found")
    return StudyListResponse(studies=[_study_response(r) for r in repository.list_studies(experience_id)])


@router.post("/experiences/{experience_id}/studies", status_code=201)
def create_study(
    experience_id: str, body: StudyWrite,
    principal: Annotated[Principal, Depends(require_permission(Permission.CREATE_STUDIES))],
    _: Annotated[Principal, Depends(require_csrf)],
    repository: Annotated[ControlPlaneRepository, Depends(get_control_repository)],
) -> dict:
    experience = repository.get_experience(experience_id)
    if experience is None: raise HTTPException(status_code=404, detail="Experience not found")
    if experience["status"] != "published": raise HTTPException(status_code=409, detail="Studies can only be created for a published Experience")
    if body.experience_id != experience_id: raise HTTPException(status_code=422, detail="Experience identity mismatch")
    record = repository.save_study(None, experience_id=experience_id, name=body.name, priority=body.priority,
        eligibility_rules=body.eligibility_rules,
        config={"schema_version": "1.0.0", "timing_rules": body.timing_rules, "survey_policy": body.survey_policy, "aois": body.aois, "questions": body.questions, "gaze_required": body.gaze_required},
        actor_id=principal.user_id, actor_role=principal.role.value)
    return _study_response(record)


@router.put("/studies/{study_id}")
def update_study(
    study_id: str, body: StudyWrite,
    principal: Annotated[Principal, Depends(require_permission(Permission.EDIT_STUDIES))],
    _: Annotated[Principal, Depends(require_csrf)],
    repository: Annotated[ControlPlaneRepository, Depends(get_control_repository)],
) -> dict:
    existing = repository.get_study(study_id)
    if existing is None: raise HTTPException(status_code=404, detail="Study not found")
    if existing["status"] != "draft": raise HTTPException(status_code=409, detail="Published Study configurations are immutable")
    try:
        record = repository.save_study(study_id, experience_id=body.experience_id, name=body.name,
            priority=body.priority, eligibility_rules=body.eligibility_rules,
            config={"schema_version": "1.0.0", "timing_rules": body.timing_rules, "survey_policy": body.survey_policy, "aois": body.aois, "questions": body.questions, "gaze_required": body.gaze_required},
            actor_id=principal.user_id, actor_role=principal.role.value)
    except ValueError as exc: raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _study_response(record)


@router.post("/studies/{study_id}/publish")
def publish_study(
    study_id: str,
    principal: Annotated[Principal, Depends(require_permission(Permission.PUBLISH_STUDIES))],
    _: Annotated[Principal, Depends(require_csrf)],
    repository: Annotated[ControlPlaneRepository, Depends(get_control_repository)],
) -> dict:
    existing = repository.get_study(study_id)
    if existing is None: raise HTTPException(status_code=404, detail="Study not found")
    experience = repository.get_experience(existing["experience_id"])
    if not experience or experience["status"] != "published":
        raise HTTPException(status_code=409, detail="The parent Experience must be published first")
    try: record = repository.publish_study(study_id, actor_id=principal.user_id, actor_role=principal.role.value)
    except ValueError as exc: raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _study_response(record)


@router.post("/studies/{study_id}/archive")
def archive_study(
    study_id: str,
    principal: Annotated[Principal, Depends(require_permission(Permission.ARCHIVE_STUDIES))],
    _: Annotated[Principal, Depends(require_csrf)],
    repository: Annotated[ControlPlaneRepository, Depends(get_control_repository)],
) -> dict:
    try: record = repository.archive_study(study_id, actor_id=principal.user_id, actor_role=principal.role.value)
    except ValueError as exc: raise HTTPException(status_code=409, detail=str(exc)) from exc
    if record is None: raise HTTPException(status_code=404, detail="Study not found")
    return _study_response(record)


@router.post("/experiences/{experience_id}/assign")
def assign_studies(
    experience_id: str, body: AssignmentRequest, response: Response,
    repository: Annotated[ControlPlaneRepository, Depends(get_control_repository)],
    origin_header: Annotated[str | None, Header(alias="Origin")] = None,
) -> dict:
    if not origin_header: raise HTTPException(status_code=403, detail="A browser Origin header is required")
    try: origin = canonicalize_origin(origin_header)
    except ValueError as exc: raise HTTPException(status_code=403, detail="Origin is not authorized") from exc
    if not repository.is_origin_authorized(experience_id, origin):
        raise HTTPException(status_code=403, detail="Origin is not authorized")
    try:
        assignments = repository.assign_studies(experience_id, body.session_id, body.attributes, body.strategy)
    except ValueError as exc: raise HTTPException(status_code=409, detail=str(exc)) from exc
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Vary"] = "Origin"
    return {"schema_version": "1.0.0", "session_id": body.session_id, "assignments": assignments}


def _validate_participant_origin(experience_id: str, origin_header: str | None,
                                 repository: ControlPlaneRepository) -> str:
    if not origin_header:
        raise HTTPException(status_code=403, detail="A browser Origin header is required")
    try: origin = canonicalize_origin(origin_header)
    except ValueError as exc: raise HTTPException(status_code=403, detail="Origin is not authorized") from exc
    if not repository.is_origin_authorized(experience_id, origin):
        raise HTTPException(status_code=403, detail="Origin is not authorized")
    return origin


def _study_assignment(session_id: str, study_id: str, repository: ControlPlaneRepository) -> tuple[dict, dict]:
    assignment = repository.get_assignment(session_id)
    if not assignment:
        raise HTTPException(status_code=404, detail="Participant session not found")
    item = next((x for x in assignment["assignments"] if x["study_id"] == study_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Study was not assigned to this session")
    if item["config_version"] != item["study_config"].get("config_version"):
        raise HTTPException(status_code=409, detail="Pinned Study configuration is inconsistent")
    return assignment, item


@participant_router.post("/sessions/bootstrap", response_model=SessionBootstrapResponse)
def create_session_bootstrap(
    body: BootstrapRequest, response: Response,
    repository: Annotated[ControlPlaneRepository, Depends(get_control_repository)],
    origin_header: Annotated[str | None, Header(alias="Origin")] = None,
    participant_cookie: Annotated[str | None, Cookie(alias=PARTICIPANT_SESSION_COOKIE)] = None,
    new_session: Annotated[bool, Query()] = False,
) -> SessionBootstrapResponse:
    """Create a participant session only from a published, origin-authorized Experience."""
    if body.schema_version != "1.0.0":
        raise HTTPException(status_code=406, detail=f"Unsupported SessionBootstrap schema version: {body.schema_version}")
    experience_id = body.experience_id
    if not experience_id:
        raise HTTPException(status_code=422, detail="experience_id is required")
    origin = _validate_participant_origin(experience_id, origin_header, repository)
    experience = repository.get_experience(experience_id)
    if not experience or experience["status"] != "published" or not experience.get("config_version"):
        raise HTTPException(status_code=409, detail="Experience has no published config version")
    existing = repository.find_participant_session_by_credential(participant_cookie) if participant_cookie else None
    if existing is not None and existing["experience_id"] == experience_id and not new_session:
        session_id = existing["session_id"]
        issued_at = existing["issued_at"]
        expires_at = existing["expires_at"]
        assignment = repository.get_assignment(session_id)
        if assignment is None or assignment["experience_id"] != experience_id:
            raise HTTPException(status_code=503, detail="Participant session state is inconsistent")
        assignments = assignment["assignments"]
        participant_credential = None
    else:
        session_id = str(uuid4())
        assignments = repository.assign_studies(experience_id, session_id, body.attributes, body.strategy)
        participant_credential = None
        if not assignments:
            raise HTTPException(status_code=409, detail="No published Studies are eligible for this session")
        issued_at = datetime.now(UTC)
        expires_at = issued_at + timedelta(minutes=60)
        _, participant_credential = repository.create_participant_session(
            session_id=session_id,
            experience_id=experience_id,
            issued_at=issued_at,
            expires_at=expires_at,
        )
    if not assignments:
        raise HTTPException(status_code=409, detail="No published Studies are eligible for this session")
    if participant_credential is not None:
        response.set_cookie(
            PARTICIPANT_SESSION_COOKIE, participant_credential,
            max_age=60 * 60, httponly=True, secure=participant_cookie_secure(),
            samesite="strict", path="/v1",
        )
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Vary"] = "Origin"
    return SessionBootstrapResponse(
        schema_version="1.0.0", session_id=session_id, experience_id=experience_id,
        participant_id=None, experience_config_version=experience["config_version"],
        eligible_studies=[{"study_id": item["study_id"], "config_version": item["config_version"],
                           "aoi_set_version": item["study_config"]["aoi_set_version"],
                           "question_set_version": item["study_config"]["question_set_version"],
                           "priority": item["study_config"]["priority"]} for item in assignments],
        privacy_notice_version=os.getenv("PRIVACY_NOTICE_VERSION", "1.0.0"),
        research_consent_version=os.getenv("RESEARCH_CONSENT_VERSION", "1.0.0"),
        camera_capture_supported=body.camera_capture_supported,
        issued_at=_timestamp(issued_at),
        expires_at=_timestamp(expires_at),
    )


@participant_router.post("/sessions/{session_id}/consent", response_model=ParticipantConsentResponse)
def record_participant_consent(
    session_id: str,
    body: ParticipantConsentRequest,
    response: Response,
    repository: Annotated[ControlPlaneRepository, Depends(get_control_repository)],
    participant_cookie: Annotated[str | None, Cookie(alias=PARTICIPANT_SESSION_COOKIE)] = None,
    origin_header: Annotated[str | None, Header(alias="Origin")] = None,
) -> ParticipantConsentResponse:
    """Record one authenticated, durable participant consent decision.

    The path session ID is only a routing key. The HttpOnly credential is the
    authorization source, and the exact allowed Origin is the participant
    state-changing request's CSRF boundary. No geometry or arbitrary state is
    accepted here.
    """
    session = require_participant_session(session_id, participant_cookie, repository)
    origin = _validate_participant_origin(session["experience_id"], origin_header, repository)
    occurred_at = _participant_timestamp(body.occurred_at, "occurred_at")
    if body.scope == "camera_gaze":
        state = repository.participant_consent_state(session_id)
        research = next((item for item in state["consent"] if item["scope"] == "research_participation"), None) if state else None
        if research is None or research["decision"] != "accepted":
            raise HTTPException(status_code=409, detail="research participation consent is required before camera consent")
    try:
        stored = repository.record_participant_consent(
            session_id=session_id,
            scope=body.scope,
            decision=body.decision,
            policy_version=body.policy_version,
            occurred_at=occurred_at,
        )
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=409 if "conflict" in detail or "required" in detail else 422, detail=detail) from exc
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Vary"] = "Origin"
    return ParticipantConsentResponse(
        scope=stored["scope"], decision=stored["decision"], policy_version=stored["policy_version"],
        occurred_at=stored["occurred_at"].isoformat().replace("+00:00", "Z"), duplicate=stored["duplicate"],
    )


@participant_router.post("/sessions/{session_id}/withdraw", response_model=ParticipantWithdrawalResponse)
def withdraw_participant_session(
    session_id: str,
    body: ParticipantWithdrawalRequest,
    response: Response,
    repository: Annotated[ControlPlaneRepository, Depends(get_control_repository)],
    participant_cookie: Annotated[str | None, Cookie(alias=PARTICIPANT_SESSION_COOKIE)] = None,
    origin_header: Annotated[str | None, Header(alias="Origin")] = None,
) -> ParticipantWithdrawalResponse:
    """Withdraw an authenticated participant session immediately.

    Once the operation commits, the credential is intentionally no longer
    authorized by ``require_participant_session``. A network retry therefore
    receives 401 without changing state again; the durable operation itself is
    idempotent and no second withdrawal timestamp is written.
    """
    session = require_participant_session(session_id, participant_cookie, repository)
    origin = _validate_participant_origin(session["experience_id"], origin_header, repository)
    occurred_at = _participant_timestamp(body.occurred_at, "occurred_at")
    try:
        stored = repository.withdraw_participant_session(session_id, occurred_at=occurred_at)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Vary"] = "Origin"
    return ParticipantWithdrawalResponse(
        status="withdrawn", withdrawn_at=stored["withdrawn_at"].isoformat().replace("+00:00", "Z"),
    )


@participant_router.post("/sessions/{session_id}/survey-responses", response_model=SurveySubmissionResponse)
def persist_participant_survey_submission(
    session_id: str,
    body: SurveySubmissionRequest,
    response: Response,
    repository: Annotated[ControlPlaneRepository, Depends(get_control_repository)],
    telemetry_repository: Annotated[TelemetryRepository, Depends(get_telemetry_repository)],
    participant_cookie: Annotated[str | None, Cookie(alias=PARTICIPANT_SESSION_COOKIE)] = None,
    origin_header: Annotated[str | None, Header(alias="Origin")] = None,
) -> SurveySubmissionResponse:
    """Persist an SDK survey submission after server-side session/config validation."""
    session = require_participant_session(session_id, participant_cookie, repository)
    origin = _validate_participant_origin(session["experience_id"], origin_header, repository)
    if body.session_id != session_id:
        raise HTTPException(status_code=422, detail="survey submission path and body session_id do not match")
    try:
        stored = repository.persist_survey_submission(body.model_dump())
    except ValueError as exc:
        detail = str(exc)
        status_code = 409 if "conflict" in detail or "identity" in detail else 422
        raise HTTPException(status_code=status_code, detail=detail) from exc
    assignment = repository.get_assignment(session_id)
    ratios: dict[str, float | None] = {}
    for item in (assignment or {}).get("assignments", []):
        config = item.get("study_config", {}) if isinstance(item, dict) else {}
        questions = config.get("question_config", {}).get("questions", []) if isinstance(config, dict) else []
        total = len(questions)
        answered = sum(1 for entry in stored["responses"] if entry["study_id"] == item.get("study_id"))
        ratios[item.get("study_id")] = answered / total if total else None
    persist_non_gaze_feature_records(
        session_id=session_id,
        experience_id=session["experience_id"],
        assignments=(assignment or {}).get("assignments", []),
        telemetry_repository=telemetry_repository,
        survey_completion_ratios=ratios,
    )
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Vary"] = "Origin"
    return SurveySubmissionResponse(
        submission_id=stored["submission_id"], session_id=stored["session_id"],
        responses=stored["responses"], duplicate=stored["duplicate"],
    )


@participant_router.get("/sessions/{session_id}/survey-responses")
def list_participant_survey_submissions(
    session_id: str,
    response: Response,
    repository: Annotated[ControlPlaneRepository, Depends(get_control_repository)],
    participant_cookie: Annotated[str | None, Cookie(alias=PARTICIPANT_SESSION_COOKIE)] = None,
    origin_header: Annotated[str | None, Header(alias="Origin")] = None,
) -> dict:
    """Retrieve only survey submissions belonging to the authenticated session."""
    session = require_participant_session(session_id, participant_cookie, repository)
    origin = _validate_participant_origin(session["experience_id"], origin_header, repository)
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Vary"] = "Origin"
    return {"schema_version": "1.0.0", "session_id": session_id,
            "submissions": repository.list_survey_submissions(session_id)}


@participant_router.post(
    "/sessions/{session_id}/studies/{study_id}/trials/{trial_id}/geometry",
    response_model=GeometrySubmissionResponse,
)
def submit_participant_geometry(
    session_id: str,
    study_id: str,
    trial_id: str,
    body: GeometrySubmissionRequest,
    response: Response,
    repository: Annotated[ControlPlaneRepository, Depends(get_control_repository)],
    telemetry_repository: Annotated[TelemetryRepository, Depends(get_telemetry_repository)],
    participant_cookie: Annotated[str | None, Cookie(alias=PARTICIPANT_SESSION_COOKIE)] = None,
    origin_header: Annotated[str | None, Header(alias="Origin")] = None,
) -> GeometrySubmissionResponse:
    """Validate and persist one study/trial-scoped geometry snapshot.

    Route and body identifiers are selectors only. Assignment, consent, AOI
    version, trial boundaries, and the trusted provenance are server-owned.
    """
    session = require_participant_session(session_id, participant_cookie, repository)
    origin = _validate_participant_origin(session["experience_id"], origin_header, repository)
    state = repository.participant_consent_state(session_id)
    accepted_scopes = {
        item["scope"]: item["decision"] for item in (state["consent"] if state else [])
    }
    if accepted_scopes.get("research_participation") != "accepted":
        raise HTTPException(status_code=409, detail="research participation consent is required")
    if accepted_scopes.get("camera_gaze") != "accepted":
        raise HTTPException(status_code=409, detail="camera/gaze consent is required")
    if body.study_id != study_id or body.trial_id != trial_id:
        raise HTTPException(status_code=422, detail="geometry request path and body context do not match")
    assignment = repository.get_assignment(session_id)
    if assignment is None:
        raise HTTPException(status_code=409, detail="participant study assignment is unavailable")
    try:
        normalized, scope = validate_server_geometry_submission(
            body.snapshot,
            participant_session=session,
            assignment=assignment,
            study_id=study_id,
            trial_id=trial_id,
            event_repository=telemetry_repository,
        )
        duplicate = telemetry_repository.persist_server_validated_geometry_snapshot(
            normalized, trusted_scope=scope
        )
    except RecordIdentityConflict as exc:
        raise HTTPException(status_code=409, detail="geometry snapshot identity conflict") from exc
    except (GazeNormalizationError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Vary"] = "Origin"
    return GeometrySubmissionResponse(
        snapshot_id=normalized["snapshot_id"], status="duplicate" if duplicate else "accepted",
        duplicate=duplicate, provenance="server_validated",
    )


@router.get("/participant/sessions/{session_id}/studies/{study_id}/study-config")
@participant_router.get("/sessions/{session_id}/studies/{study_id}/study-config")
def get_participant_study_config(
    session_id: str, study_id: str, config_version: str, response: Response,
    repository: Annotated[ControlPlaneRepository, Depends(get_control_repository)],
    origin_header: Annotated[str | None, Header(alias="Origin")] = None,
) -> dict:
    assignment = repository.get_assignment(session_id)
    if not assignment: raise HTTPException(status_code=404, detail="Participant session not found")
    origin = _validate_participant_origin(assignment["experience_id"], origin_header, repository)
    _, item = _study_assignment(session_id, study_id, repository)
    config = item["study_config"]
    if config_version != item["config_version"]: raise HTTPException(status_code=404, detail="Pinned config version not found")
    response.headers["Access-Control-Allow-Origin"] = origin; response.headers["Vary"] = "Origin"
    return {key: config[key] for key in ("schema_version", "study_id", "experience_id", "config_version", "status", "aoi_set_version", "question_set_version", "survey_policy", "gaze_required", "priority")}


@router.get("/participant/sessions/{session_id}/studies/{study_id}/aoi-config")
@participant_router.get("/sessions/{session_id}/studies/{study_id}/aoi-config")
def get_participant_aoi_config(
    session_id: str, study_id: str, config_version: str, response: Response,
    repository: Annotated[ControlPlaneRepository, Depends(get_control_repository)],
    origin_header: Annotated[str | None, Header(alias="Origin")] = None,
) -> dict:
    assignment = repository.get_assignment(session_id)
    if not assignment: raise HTTPException(status_code=404, detail="Participant session not found")
    origin = _validate_participant_origin(assignment["experience_id"], origin_header, repository)
    _, item = _study_assignment(session_id, study_id, repository)
    config = item["study_config"]
    aoi = config["aoi_config"]
    if config_version != aoi["config_version"]: raise HTTPException(status_code=404, detail="Pinned AOI config version not found")
    response.headers["Access-Control-Allow-Origin"] = origin; response.headers["Vary"] = "Origin"
    return {"schema_version": "1.0.0", "experience_id": assignment["experience_id"], "study_id": study_id,
            "aoi_set_version": aoi["config_version"], "aois": aoi["items"]}


@router.get("/participant/sessions/{session_id}/studies/{study_id}/question-config")
@participant_router.get("/sessions/{session_id}/studies/{study_id}/question-config")
def get_participant_question_config(
    session_id: str, study_id: str, config_version: str, response: Response,
    repository: Annotated[ControlPlaneRepository, Depends(get_control_repository)],
    origin_header: Annotated[str | None, Header(alias="Origin")] = None,
) -> dict:
    assignment = repository.get_assignment(session_id)
    if not assignment: raise HTTPException(status_code=404, detail="Participant session not found")
    origin = _validate_participant_origin(assignment["experience_id"], origin_header, repository)
    _, item = _study_assignment(session_id, study_id, repository)
    config = item["study_config"]
    questions = config["question_config"]
    if config_version != config["question_set_version"]: raise HTTPException(status_code=404, detail="Pinned Question config version not found")
    response.headers["Access-Control-Allow-Origin"] = origin; response.headers["Vary"] = "Origin"
    if {"schema_version", "study_id", "question_set_version", "questions"}.issubset(questions):
        return questions
    # Existing pinned sessions may contain the earlier internal representation.
    return {"schema_version": "1.0.0", "study_id": study_id,
            "question_set_version": questions.get("config_version", config["question_set_version"]),
            "questions": questions.get("items", [])}


def _consolidated_plan(session_id: str, repository: ControlPlaneRepository) -> dict:
    assignment = repository.get_assignment(session_id)
    if not assignment: raise HTTPException(status_code=404, detail="Participant session not found")
    return consolidate_survey(session_id, assignment["assignments"])


@router.get("/participant/sessions/{session_id}/survey-plan")
@participant_router.get("/sessions/{session_id}/survey-plan")
def get_participant_survey_plan(
    session_id: str, response: Response,
    repository: Annotated[ControlPlaneRepository, Depends(get_control_repository)],
    origin_header: Annotated[str | None, Header(alias="Origin")] = None,
) -> dict:
    assignment = repository.get_assignment(session_id)
    if not assignment: raise HTTPException(status_code=404, detail="Participant session not found")
    origin = _validate_participant_origin(assignment["experience_id"], origin_header, repository)
    response.headers["Access-Control-Allow-Origin"] = origin; response.headers["Vary"] = "Origin"
    return _consolidated_plan(session_id, repository)["survey_plan"]


@router.get("/participant/sessions/{session_id}/survey-plan-details")
@participant_router.get("/sessions/{session_id}/survey-plan-details")
def get_participant_survey_plan_details(
    session_id: str, response: Response,
    repository: Annotated[ControlPlaneRepository, Depends(get_control_repository)],
    origin_header: Annotated[str | None, Header(alias="Origin")] = None,
) -> dict:
    assignment = repository.get_assignment(session_id)
    if not assignment: raise HTTPException(status_code=404, detail="Participant session not found")
    origin = _validate_participant_origin(assignment["experience_id"], origin_header, repository)
    response.headers["Access-Control-Allow-Origin"] = origin; response.headers["Vary"] = "Origin"
    return _consolidated_plan(session_id, repository)["details"]
