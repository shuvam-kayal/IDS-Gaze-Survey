"""PostgreSQL persistence for Experience registry and control-plane audit."""

from __future__ import annotations

import hashlib
import os
import secrets
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Mapped, mapped_column, sessionmaker

from services.telemetry.persistence import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


def evaluate_eligibility(rule: dict[str, Any], attributes: dict[str, Any]) -> bool:
    """Evaluate the bounded, data-only eligibility DSL; no expressions or code are executed."""
    if not rule or rule == {"all": []}:
        return True
    if "all" in rule:
        return all(evaluate_eligibility(child, attributes) for child in rule["all"])
    if "any" in rule:
        return any(evaluate_eligibility(child, attributes) for child in rule["any"])
    if "not" in rule:
        return not evaluate_eligibility(rule["not"], attributes)
    field, op, expected = rule["field"], rule["op"], rule.get("value")
    actual = attributes.get(field)
    if op == "exists": return (field in attributes) is bool(expected)
    if op == "eq": return actual == expected
    if op == "ne": return actual != expected
    if op == "in": return actual in expected if isinstance(expected, list) else False
    if op == "contains": return expected in actual if isinstance(actual, (str, list)) else False
    if op in {"gte", "lte"} and isinstance(actual, (int, float)) and not isinstance(actual, bool) and isinstance(expected, (int, float)):
        return actual >= expected if op == "gte" else actual <= expected
    return False


class ExperienceRecord(Base):
    __tablename__ = "control_experiences"

    experience_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    allowed_origins: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    config_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ControlPlaneAuditRecord(Base):
    __tablename__ = "control_plane_audit_events"

    audit_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[str] = mapped_column(String(255), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )


class StudyRecord(Base):
    __tablename__ = "control_studies"

    study_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    experience_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    eligibility_rules: Mapped[dict[str, Any]] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    config_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StudyAssignmentRecord(Base):
    __tablename__ = "control_study_assignments"

    session_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    experience_id: Mapped[str] = mapped_column(String(36), nullable=False)
    assigned_studies: Mapped[list[dict[str, Any]]] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ParticipantSessionRecord(Base):
    """Server-created participant session lifecycle state.

    The credential verifier binds possession of a server-issued cookie to this
    session. It does not identify a participant in the real world.
    """

    __tablename__ = "participant_sessions"

    session_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    experience_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    credential_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)


class ParticipantConsentRecord(Base):
    """Latest durable consent decision for one session and consent scope."""

    __tablename__ = "participant_consent_records"

    session_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("participant_sessions.session_id", ondelete="CASCADE"), primary_key=True
    )
    scope: Mapped[str] = mapped_column(String(32), primary_key=True)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(255), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SurveyResponseRecord(Base):
    """One durable answer from an authenticated participant submission."""

    __tablename__ = "participant_survey_responses"
    __table_args__ = (
        UniqueConstraint("session_id", "response_id", name="uq_survey_response_session_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    response_id: Mapped[str] = mapped_column(String(255), nullable=False)
    submission_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    experience_id: Mapped[str] = mapped_column(String(255), nullable=False)
    session_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    study_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    question_id: Mapped[str] = mapped_column(String(255), nullable=False)
    question_set_version: Mapped[str] = mapped_column(String(255), nullable=False)
    answer_type: Mapped[str] = mapped_column(String(32), nullable=False)
    answer: Mapped[Any] = mapped_column(JSON().with_variant(JSONB, "postgresql"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SurveySubmissionRecord(Base):
    """Durable submission identity, including submissions with no optional answers."""

    __tablename__ = "participant_survey_submissions"
    __table_args__ = (
        UniqueConstraint("session_id", "submission_id", name="uq_survey_submission_session_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    submission_id: Mapped[str] = mapped_column(String(255), nullable=False)
    experience_id: Mapped[str] = mapped_column(String(255), nullable=False)
    session_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ControlPlaneRepository:
    def __init__(self, engine: Engine):
        self.engine = engine
        self.sessions = sessionmaker(bind=engine, expire_on_commit=False)

    @classmethod
    def from_env(cls) -> ControlPlaneRepository:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL is required for the Experience registry")
        return cls(create_engine(database_url, pool_pre_ping=True))

    @staticmethod
    def _serialize(record: ExperienceRecord) -> dict[str, Any]:
        return {
            "experience_id": record.experience_id,
            "name": record.name,
            "allowed_origins": list(record.allowed_origins),
            "status": record.status,
            "config_version": record.config_version,
            "created_by": record.created_by,
            "updated_by": record.updated_by,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "published_at": record.published_at,
            "archived_at": record.archived_at,
        }

    def list_experiences(self) -> list[dict[str, Any]]:
        with self.sessions() as db:
            rows = db.scalars(select(ExperienceRecord).order_by(ExperienceRecord.created_at)).all()
            return [self._serialize(row) for row in rows]

    def get_experience(self, experience_id: str) -> dict[str, Any] | None:
        with self.sessions() as db:
            row = db.get(ExperienceRecord, experience_id)
            return self._serialize(row) if row else None

    def create_experience(
        self, *, name: str, allowed_origins: list[str], actor_id: str, actor_role: str
    ) -> dict[str, Any]:
        now = utc_now()
        experience = ExperienceRecord(
            experience_id=str(uuid4()),
            name=name,
            allowed_origins=allowed_origins,
            status="draft",
            created_by=actor_id,
            updated_by=actor_id,
            created_at=now,
            updated_at=now,
        )
        with self.sessions.begin() as db:
            db.add(experience)
            self._audit(
                db, actor_id, actor_role, "experience.created", experience.experience_id,
                {"status": "draft", "allowed_origins": allowed_origins},
            )
        return self._serialize(experience)

    def update_experience(
        self,
        experience_id: str,
        *,
        name: str,
        allowed_origins: list[str],
        actor_id: str,
        actor_role: str,
    ) -> dict[str, Any] | None:
        now = utc_now()
        with self.sessions.begin() as db:
            row = db.get(ExperienceRecord, experience_id)
            if row is None:
                return None
            if row.status != "draft":
                raise ValueError("Only draft Experiences can be edited")
            row.name, row.allowed_origins = name, allowed_origins
            row.updated_by, row.updated_at = actor_id, now
            self._audit(
                db, actor_id, actor_role, "experience.updated", experience_id,
                {"name": name, "allowed_origins": allowed_origins},
            )
        return self.get_experience(experience_id)

    def set_lifecycle(
        self, experience_id: str, *, target_status: str, actor_id: str, actor_role: str
    ) -> dict[str, Any] | None:
        now = utc_now()
        action = "experience.published" if target_status == "published" else "experience.archived"
        with self.sessions.begin() as db:
            row = db.get(ExperienceRecord, experience_id)
            if row is None:
                return None
            if target_status == "published" and row.status != "draft":
                raise ValueError("Only draft Experiences can be published")
            if target_status == "archived" and row.status == "archived":
                raise ValueError("Experience is already archived")
            row.status = target_status
            row.updated_by, row.updated_at = actor_id, now
            if target_status == "published":
                row.published_at = now
                row.config_version = f"experience-config-v1:{uuid4()}"
            else:
                row.archived_at = now
            self._audit(db, actor_id, actor_role, action, experience_id, {"status": target_status})
        return self.get_experience(experience_id)

    def is_origin_authorized(self, experience_id: str, origin: str) -> bool:
        with self.sessions() as db:
            record = db.get(ExperienceRecord, experience_id)
            return bool(
                record
                and record.status == "published"
                and origin in record.allowed_origins
            )

    @staticmethod
    def _serialize_study(row: StudyRecord) -> dict[str, Any]:
        return {
            "study_id": row.study_id, "experience_id": row.experience_id,
            "name": row.name, "status": row.status, "priority": row.priority,
            "eligibility_rules": row.eligibility_rules, "config_version": row.config_version,
            "config": row.config, "created_by": row.created_by, "updated_by": row.updated_by,
            "created_at": row.created_at, "updated_at": row.updated_at,
            "published_at": row.published_at, "archived_at": row.archived_at,
        }

    def list_studies(self, experience_id: str) -> list[dict[str, Any]]:
        with self.sessions() as db:
            rows = db.scalars(select(StudyRecord).where(StudyRecord.experience_id == experience_id).order_by(StudyRecord.created_at, StudyRecord.study_id)).all()
            return [self._serialize_study(row) for row in rows]

    def get_study(self, study_id: str) -> dict[str, Any] | None:
        with self.sessions() as db:
            row = db.get(StudyRecord, study_id)
            return self._serialize_study(row) if row else None

    def save_study(self, study_id: str | None, *, experience_id: str, name: str, priority: int,
                   eligibility_rules: dict[str, Any], config: dict[str, Any], actor_id: str,
                   actor_role: str) -> dict[str, Any]:
        now = utc_now()
        with self.sessions.begin() as db:
            row = db.get(StudyRecord, study_id) if study_id else None
            if study_id and (row is None or row.status != "draft"):
                raise ValueError("Only existing draft Studies can be edited")
            if row is None:
                row = StudyRecord(study_id=str(uuid4()), experience_id=experience_id, name=name,
                                  status="draft", priority=priority, eligibility_rules=eligibility_rules,
                                  config=config, created_by=actor_id, updated_by=actor_id,
                                  created_at=now, updated_at=now)
                db.add(row)
                action = "study.created"
            else:
                if row.experience_id != experience_id:
                    raise ValueError("A Study cannot be moved to another Experience")
                row.name, row.priority = name, priority
                row.eligibility_rules, row.config = eligibility_rules, config
                row.updated_by, row.updated_at = actor_id, now
                action = "study.updated"
            self._audit(db, actor_id, actor_role, action, row.study_id,
                        {"experience_id": experience_id, "name": name}, target_type="study")
            result_id = row.study_id
        return self.get_study(result_id)

    def publish_study(self, study_id: str, *, actor_id: str, actor_role: str) -> dict[str, Any] | None:
        now = utc_now()
        with self.sessions.begin() as db:
            row = db.get(StudyRecord, study_id)
            if row is None:
                return None
            if row.status != "draft":
                raise ValueError("Only draft Studies can be published")
            row.status, row.published_at, row.updated_at, row.updated_by = "published", now, now, actor_id
            row.config_version = f"study-config-v1:{uuid4()}"
            aoi_version, question_version = f"aoi-config-v1:{uuid4()}", f"question-config-v1:{uuid4()}"
            row.config = {**row.config, "schema_version": "1.0.0", "config_version": row.config_version,
                          "study_id": row.study_id, "experience_id": row.experience_id,
                          "status": "active", "aoi_set_version": aoi_version,
                          "question_set_version": question_version,
                          "survey_policy": row.config.get("survey_policy", {"timing": "after_exposure", "consolidation": "deduplicate_by_question_id"}),
                          "gaze_required": False, "priority": row.priority,
                          "aoi_config": {"schema_version": "1.0.0", "config_version": aoi_version,
                                         "items": row.config.get("aois", [])},
                          "question_config": {"schema_version": "1.0.0", "study_id": row.study_id,
                                              "question_set_version": question_version,
                                              "questions": row.config.get("questions", [])}}
            self._audit(db, actor_id, actor_role, "study.published", study_id,
                        {"config_version": row.config_version}, target_type="study")
        return self.get_study(study_id)

    def archive_study(self, study_id: str, *, actor_id: str, actor_role: str) -> dict[str, Any] | None:
        now = utc_now()
        with self.sessions.begin() as db:
            row = db.get(StudyRecord, study_id)
            if row is None:
                return None
            if row.status == "archived":
                raise ValueError("Study is already archived")
            row.status, row.archived_at, row.updated_at, row.updated_by = "archived", now, now, actor_id
            self._audit(db, actor_id, actor_role, "study.archived", study_id, {}, target_type="study")
        return self.get_study(study_id)

    def assign_studies(self, experience_id: str, session_id: str, attributes: dict[str, Any],
                       strategy: str) -> list[dict[str, Any]]:
        with self.sessions.begin() as db:
            existing = db.get(StudyAssignmentRecord, session_id)
            if existing:
                if existing.experience_id != experience_id:
                    raise ValueError("Session is already assigned to a different Experience")
                return existing.assigned_studies
            rows = db.scalars(select(StudyRecord).where(
                StudyRecord.experience_id == experience_id, StudyRecord.status == "published"
            )).all()
            eligible = [row for row in rows if evaluate_eligibility(row.eligibility_rules, attributes)]
            eligible.sort(key=lambda row: (-row.priority, row.study_id))
            chosen = eligible[:1] if strategy == "prioritized" else eligible
            assignments = [{"study_id": row.study_id, "config_version": row.config_version,
                            "study_config": row.config} for row in chosen]
            if not assignments:
                return []
            db.add(StudyAssignmentRecord(session_id=session_id, experience_id=experience_id,
                                         assigned_studies=assignments, assigned_at=utc_now()))
            return assignments

    def get_assignment(self, session_id: str) -> dict[str, Any] | None:
        with self.sessions() as db:
            row = db.get(StudyAssignmentRecord, session_id)
            return ({"session_id": row.session_id, "experience_id": row.experience_id,
                     "assignments": row.assigned_studies, "assigned_at": row.assigned_at} if row else None)

    def list_consented_session_ids_for_study(self, study_id: str) -> list[str]:
        """Return only non-withdrawn sessions with recorded research consent.

        Assignment JSON is versioned and small; filtering it in Python keeps
        the lookup portable across the SQLite test adapter and PostgreSQL.
        """
        with self.sessions() as db:
            assignments = db.scalars(select(StudyAssignmentRecord)).all()
            candidates = {
                row.session_id
                for row in assignments
                if any(item.get("study_id") == study_id for item in row.assigned_studies)
            }
            if not candidates:
                return []
            sessions = db.scalars(select(ParticipantSessionRecord).where(
                ParticipantSessionRecord.session_id.in_(candidates),
                ParticipantSessionRecord.status != "withdrawn",
            )).all()
            live = {row.session_id for row in sessions}
            consents = db.scalars(select(ParticipantConsentRecord).where(
                ParticipantConsentRecord.session_id.in_(live),
                ParticipantConsentRecord.scope == "research_participation",
                ParticipantConsentRecord.decision == "accepted",
            )).all() if live else []
            return sorted({row.session_id for row in consents})

    @staticmethod
    def _session_dict(row: ParticipantSessionRecord) -> dict[str, Any]:
        return {
            "session_id": row.session_id,
            "experience_id": row.experience_id,
            "status": row.status,
            "issued_at": row.issued_at,
            "expires_at": row.expires_at,
            "closed_at": row.closed_at,
            "withdrawn_at": row.withdrawn_at,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def create_participant_session(
        self, *, session_id: str, experience_id: str, issued_at: datetime, expires_at: datetime
    ) -> tuple[dict[str, Any], str]:
        """Persist server-issued session state and return a one-time raw credential.

        The raw credential is returned only to the bootstrap caller so it can
        become an HttpOnly cookie. It is never stored or returned by lookup.
        """
        if expires_at <= issued_at:
            raise ValueError("participant session expiry must be after issuance")
        now = utc_now()
        with self.sessions.begin() as db:
            row = db.get(ParticipantSessionRecord, session_id)
            if row is not None:
                if row.experience_id != experience_id or row.issued_at != issued_at or row.expires_at != expires_at:
                    raise ValueError("participant session identity conflict")
                raise ValueError("participant session already exists without a new binding")
            raw_credential = secrets.token_urlsafe(32)
            row = ParticipantSessionRecord(
                session_id=session_id, experience_id=experience_id, status="open",
                issued_at=issued_at, expires_at=expires_at, created_at=now, updated_at=now,
                credential_hash=hashlib.sha256(raw_credential.encode("utf-8")).hexdigest(),
            )
            db.add(row)
        return self._session_dict(row), raw_credential

    def get_participant_session(self, session_id: str) -> dict[str, Any] | None:
        with self.sessions() as db:
            row = db.get(ParticipantSessionRecord, session_id)
            return self._session_dict(row) if row else None

    def verify_participant_session(self, *, session_id: str, credential: str) -> dict[str, Any] | None:
        """Verify the credential/session binding without returning secrets."""
        if not isinstance(credential, str) or not credential:
            return None
        digest = hashlib.sha256(credential.encode("utf-8")).hexdigest()
        now = utc_now()
        with self.sessions() as db:
            row = db.scalar(select(ParticipantSessionRecord).where(
                ParticipantSessionRecord.session_id == session_id,
                ParticipantSessionRecord.credential_hash == digest,
            ))
            if row is None or row.status != "open" or row.expires_at <= now:
                return None
            return self._session_dict(row)

    def find_participant_session_by_credential(self, credential: str) -> dict[str, Any] | None:
        """Find one live session for a credential without exposing its hash."""
        if not isinstance(credential, str) or not credential:
            return None
        digest = hashlib.sha256(credential.encode("utf-8")).hexdigest()
        now = utc_now()
        with self.sessions() as db:
            row = db.scalar(select(ParticipantSessionRecord).where(
                ParticipantSessionRecord.credential_hash == digest,
            ))
            if row is None or row.status != "open" or row.expires_at <= now:
                return None
            return self._session_dict(row)

    def record_participant_consent(
        self, *, session_id: str, scope: str, decision: str,
        policy_version: str, occurred_at: datetime,
    ) -> dict[str, Any]:
        """Persist one consent decision per session and scope.

        The route layer authenticates the participant. This repository method
        also enforces the dependency between the two consent scopes so an
        internal caller cannot grant camera consent without research consent.
        """
        if scope not in {"research_participation", "camera_gaze"}:
            raise ValueError("unsupported participant consent scope")
        if decision not in {"accepted", "declined"}:
            raise ValueError("unsupported participant consent decision")
        if not policy_version:
            raise ValueError("policy_version is required")
        with self.sessions.begin() as db:
            session = db.get(ParticipantSessionRecord, session_id)
            if session is None:
                raise ValueError("unknown participant session")
            if session.status in {"withdrawn", "closed"} or session.expires_at <= occurred_at:
                raise ValueError("participant session is not accepting consent")
            if scope == "camera_gaze":
                research = db.get(ParticipantConsentRecord, (session_id, "research_participation"))
                if research is None or research.decision != "accepted":
                    raise ValueError("research participation consent is required before camera consent")
            existing = db.get(ParticipantConsentRecord, (session_id, scope))
            if existing is not None:
                # Consent is durable state, not an append-only event keyed by
                # the browser's observation timestamp. A refreshed participant
                # page may replay the same decision with a new timestamp. Keep
                # the original occurrence time and make that retry idempotent;
                # changing the decision or policy remains a conflict.
                if (existing.decision, existing.policy_version) != (decision, policy_version):
                    raise ValueError("participant consent decision conflict")
                return {"session_id": existing.session_id, "scope": existing.scope,
                        "decision": existing.decision, "policy_version": existing.policy_version,
                        "occurred_at": existing.occurred_at, "updated_at": existing.updated_at,
                        "duplicate": True}
            now = utc_now()
            db.add(ParticipantConsentRecord(
                session_id=session_id, scope=scope, decision=decision,
                policy_version=policy_version, occurred_at=occurred_at, updated_at=now,
            ))
            session.updated_at = now
        return {"session_id": session_id, "scope": scope, "decision": decision,
                "policy_version": policy_version, "occurred_at": occurred_at, "updated_at": now,
                "duplicate": False}

    def withdraw_participant_session(self, session_id: str, *, occurred_at: datetime) -> dict[str, Any]:
        """Idempotently revoke a server-created participant session."""
        with self.sessions.begin() as db:
            row = db.get(ParticipantSessionRecord, session_id)
            if row is None:
                raise ValueError("unknown participant session")
            if row.withdrawn_at is None:
                row.withdrawn_at = occurred_at
                row.status = "withdrawn"
                row.updated_at = utc_now()
            return self._session_dict(row)

    def participant_consent_state(self, session_id: str) -> dict[str, Any] | None:
        with self.sessions() as db:
            session = db.get(ParticipantSessionRecord, session_id)
            if session is None:
                return None
            records = db.scalars(
                select(ParticipantConsentRecord).where(
                    ParticipantConsentRecord.session_id == session_id
                ).order_by(ParticipantConsentRecord.scope)
            ).all()
            return {"session": self._session_dict(session), "consent": [
                {"scope": row.scope, "decision": row.decision,
                 "policy_version": row.policy_version, "occurred_at": row.occurred_at,
                 "updated_at": row.updated_at} for row in records
            ]}

    @staticmethod
    def _survey_question_map(assignment: dict[str, Any]) -> dict[str, dict[str, Any]]:
        config = assignment.get("study_config")
        question_config = config.get("question_config") if isinstance(config, dict) else None
        questions = (question_config.get("questions", question_config.get("items", []))
                     if isinstance(question_config, dict) else None)
        if not isinstance(questions, list):
            raise ValueError("assigned Study question configuration is unavailable")
        result = {}
        for question in questions:
            if isinstance(question, dict) and isinstance(question.get("question_id"), str):
                result[question["question_id"]] = question
        return result

    @staticmethod
    def _validate_survey_answer(question: dict[str, Any], answer: Any) -> None:
        answer_type = question.get("answer_type")
        options = {item.get("option_id") for item in question.get("options", []) if isinstance(item, dict)}
        if answer_type in {"single_choice", "scale"}:
            if not isinstance(answer, str) or answer not in options:
                raise ValueError("survey answer does not match the pinned option set")
        elif answer_type == "multi_choice":
            if (not isinstance(answer, list) or not answer or
                    any(not isinstance(item, str) or item not in options for item in answer) or
                    len(set(answer)) != len(answer)):
                raise ValueError("survey answer does not match the pinned option set")
        elif answer_type == "boolean":
            if not isinstance(answer, bool):
                raise ValueError("survey boolean answer is invalid")
        elif answer_type == "free_text":
            if not isinstance(answer, str):
                raise ValueError("survey free-text answer is invalid")
        else:
            raise ValueError("survey answer type is unsupported")

    @staticmethod
    def _survey_row_value(row: SurveyResponseRecord) -> dict[str, Any]:
        return {
            "response_id": row.response_id,
            "submission_id": row.submission_id,
            "experience_id": row.experience_id,
            "session_id": row.session_id,
            "study_id": row.study_id,
            "question_id": row.question_id,
            "question_set_version": row.question_set_version,
            "answer_type": row.answer_type,
            "answer": row.answer,
        }

    def persist_survey_submission(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate and durably persist one authorized SDK SurveySubmission."""
        required = {"submission_id", "session_id", "responses"}
        if not isinstance(payload, dict) or set(payload) != required:
            raise ValueError("survey submission has invalid fields")
        submission_id, session_id, responses = payload["submission_id"], payload["session_id"], payload["responses"]
        if (not isinstance(submission_id, str) or not submission_id.strip() or len(submission_id) > 255 or
                not isinstance(session_id, str) or not session_id.strip() or len(session_id) > 255):
            raise ValueError("survey submission identity is invalid")
        if not isinstance(responses, list):
            raise ValueError("survey submission responses must be an array")

        with self.sessions.begin() as db:
            session = db.get(ParticipantSessionRecord, session_id)
            if session is None or session.status != "open" or session.expires_at <= utc_now():
                raise ValueError("participant session is not accepting survey responses")
            research = db.get(ParticipantConsentRecord, (session_id, "research_participation"))
            if research is None or research.decision != "accepted":
                raise ValueError("research participation consent is required")
            assignment_row = db.get(StudyAssignmentRecord, session_id)
            if assignment_row is None or assignment_row.experience_id != session.experience_id:
                raise ValueError("participant Study assignment is unavailable")

            assignments = {item.get("study_id"): item for item in assignment_row.assigned_studies if isinstance(item, dict)}
            normalized: list[dict[str, Any]] = []
            seen_response_ids: set[str] = set()
            question_ids_by_study: dict[str, set[str]] = {}
            for response in responses:
                if not isinstance(response, dict):
                    raise ValueError("survey response must be an object")
                allowed = {"response_id", "submission_id", "experience_id", "session_id", "participant_id", "study_id", "question_id", "question_set_version", "answer_type", "answer"}
                if set(response) - allowed or not {"response_id", "submission_id", "experience_id", "session_id", "study_id", "question_id", "question_set_version", "answer_type", "answer"}.issubset(response):
                    raise ValueError("survey response has invalid fields")
                if response.get("submission_id") != submission_id or response.get("session_id") != session_id:
                    raise ValueError("survey response does not match submission session")
                if response.get("experience_id") != session.experience_id:
                    raise ValueError("survey response does not match session Experience")
                if response.get("participant_id") is not None:
                    raise ValueError("participant_id must be server-assigned")
                response_id = response.get("response_id")
                if not isinstance(response_id, str) or not response_id.strip() or len(response_id) > 255 or response_id in seen_response_ids:
                    raise ValueError("survey response_id is invalid or duplicated")
                seen_response_ids.add(response_id)
                study_id = response.get("study_id")
                assignment = assignments.get(study_id)
                if assignment is None:
                    raise ValueError("survey response Study is not assigned to this session")
                config = assignment.get("study_config", {})
                question_version = config.get("question_set_version")
                if response.get("question_set_version") != question_version:
                    raise ValueError("survey response question-set version does not match the pinned Study")
                question = self._survey_question_map(assignment).get(response.get("question_id"))
                if question is None or response.get("answer_type") != question.get("answer_type"):
                    raise ValueError("survey response question is not in the pinned Study config")
                self._validate_survey_answer(question, response.get("answer"))
                question_ids_by_study.setdefault(study_id, set()).add(response["question_id"])
                normalized.append({key: response[key] for key in ("response_id", "submission_id", "experience_id", "session_id", "study_id", "question_id", "question_set_version", "answer_type", "answer")})

            answered_question_ids = {item["question_id"] for item in normalized}
            for study_id, assignment in assignments.items():
                questions = self._survey_question_map(assignment)
                for question_id, question in questions.items():
                    if question.get("required") is not True or question_id in question_ids_by_study.get(study_id, set()):
                        continue
                    policy = assignment.get("study_config", {}).get("survey_policy", {})
                    if policy.get("consolidation") != "deduplicate_by_question_id":
                        raise ValueError("survey submission is missing a required answer")
                    semantic = {key: value for key, value in question.items() if key not in {"version", "order"}}
                    shared_required = any(
                        question_id in other_questions and
                        {key: value for key, value in other_questions[question_id].items() if key not in {"version", "order"}} == semantic
                        for other_id, other_assignment in assignments.items()
                        if other_id != study_id
                        for other_questions in [self._survey_question_map(other_assignment)]
                    )
                    if not shared_required or question_id not in answered_question_ids:
                        raise ValueError("survey submission is missing a required answer")

            normalized.sort(key=lambda item: item["response_id"])
            submission_row = db.scalar(select(SurveySubmissionRecord).where(
                SurveySubmissionRecord.session_id == session_id,
                SurveySubmissionRecord.submission_id == submission_id,
            ))
            existing = db.scalars(select(SurveyResponseRecord).where(
                SurveyResponseRecord.session_id == session_id,
                SurveyResponseRecord.submission_id == submission_id,
            ).order_by(SurveyResponseRecord.response_id)).all()
            existing_values = [self._survey_row_value(row) for row in existing]
            if submission_row is not None and existing_values == normalized:
                return {"submission_id": submission_id, "session_id": session_id, "responses": existing_values, "duplicate": True}
            if submission_row is not None:
                raise ValueError("survey submission identity conflict")

            db.add(SurveySubmissionRecord(
                submission_id=submission_id, experience_id=session.experience_id,
                session_id=session_id, created_at=utc_now(),
            ))
            for item in normalized:
                prior = db.scalar(select(SurveyResponseRecord).where(
                    SurveyResponseRecord.session_id == session_id,
                    SurveyResponseRecord.response_id == item["response_id"],
                ))
                if prior is not None:
                    raise ValueError("survey response identity conflict")
                db.add(SurveyResponseRecord(**item, created_at=utc_now()))
            return {"submission_id": submission_id, "session_id": session_id, "responses": normalized, "duplicate": False}

    def list_survey_submissions(self, session_id: str) -> list[dict[str, Any]]:
        with self.sessions() as db:
            submissions = db.scalars(select(SurveySubmissionRecord).where(
                SurveySubmissionRecord.session_id == session_id,
            ).order_by(SurveySubmissionRecord.created_at, SurveySubmissionRecord.submission_id)).all()
            rows = db.scalars(select(SurveyResponseRecord).where(
                SurveyResponseRecord.session_id == session_id,
            ).order_by(SurveyResponseRecord.created_at, SurveyResponseRecord.response_id)).all()
            grouped: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                grouped.setdefault(row.submission_id, []).append(self._survey_row_value(row))
            return [{"submission_id": row.submission_id, "session_id": session_id,
                     "responses": grouped.get(row.submission_id, [])} for row in submissions]

    def list_audit_events(self, *, target_id: str | None = None) -> list[dict[str, Any]]:
        with self.sessions() as db:
            statement = select(ControlPlaneAuditRecord).order_by(ControlPlaneAuditRecord.occurred_at)
            if target_id:
                statement = statement.where(ControlPlaneAuditRecord.target_id == target_id)
            rows = db.scalars(statement).all()
            return [
                {
                    "audit_id": row.audit_id,
                    "actor_id": row.actor_id,
                    "actor_role": row.actor_role,
                    "action": row.action,
                    "target_type": row.target_type,
                    "target_id": row.target_id,
                    "occurred_at": row.occurred_at,
                    "details": row.details,
                }
                for row in rows
            ]

    @staticmethod
    def _audit(db, actor_id: str, actor_role: str, action: str, target_id: str, details: dict,
               target_type: str = "experience") -> None:
        db.add(
            ControlPlaneAuditRecord(
                audit_id=str(uuid4()),
                actor_id=actor_id,
                actor_role=actor_role,
                action=action,
                target_type=target_type,
                target_id=target_id,
                occurred_at=utc_now(),
                details=details,
            )
        )
