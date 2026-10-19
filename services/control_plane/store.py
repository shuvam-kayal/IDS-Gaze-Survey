"""PostgreSQL persistence for Experience registry and control-plane audit."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Integer, String, create_engine, select
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
                          "question_config": {"schema_version": "1.0.0", "config_version": question_version,
                                              "items": row.config.get("questions", [])}}
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
