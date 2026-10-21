"""P4 SQLAlchemy 2.x persistence; shared Alembic migration wiring is integrator-owned."""
from __future__ import annotations

import base64
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import DateTime, Index, String, UniqueConstraint, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.types import JSON

from .engine import AnalysisError

JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")
RETENTION_DAYS = 90


class Base(DeclarativeBase):
    pass


class AnalysisRow(Base):
    __tablename__ = "p4_analysis_results"
    __table_args__ = (
        UniqueConstraint("analysis_request_id", "study_id", name="uq_p4_analysis_request_study"),
        Index("ix_p4_analysis_study_created", "study_id", "created_at", "analysis_id"),
    )

    analysis_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    analysis_request_id: Mapped[str] = mapped_column(String(200), nullable=False)
    study_id: Mapped[str] = mapped_column(String(200), nullable=False)
    feature_set_version: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    result_payload: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)


class AnalysisRepository:
    """PostgreSQL repository configured only from DATABASE_URL."""

    def __init__(self, database_url: str | None = None, *, session_factory: sessionmaker[Session] | None = None):
        if session_factory is None:
            url = database_url or os.environ.get("DATABASE_URL")
            if not url:
                raise RuntimeError("DATABASE_URL must identify the shared PostgreSQL 16 database")
            if not url.startswith("postgresql+psycopg://"):
                raise RuntimeError("Analytics persistence requires PostgreSQL via DATABASE_URL; SQLite and other databases are unsupported")
            self.engine = create_engine(url, pool_pre_ping=True)
            self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        else:
            self.engine = None
            self.sessions = session_factory

    @staticmethod
    def _row(request: dict[str, Any], result: dict[str, Any]) -> AnalysisRow:
        created = datetime.fromisoformat(result["created_at"])
        return AnalysisRow(
            analysis_id=result["analysis_id"], analysis_request_id=request["analysis_request_id"],
            study_id=result["study_id"], feature_set_version=result["feature_set_version"],
            status=result["status"], created_at=created,
            expires_at=created + timedelta(days=RETENTION_DAYS),
            request_payload=request, result_payload=result,
        )

    def save(self, request: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        with self.sessions.begin() as session:
            existing = session.scalar(select(AnalysisRow).where(
                AnalysisRow.analysis_request_id == request["analysis_request_id"],
                AnalysisRow.study_id == request["study_id"],
            ))
            if existing:
                if existing.request_payload != request:
                    raise AnalysisError("idempotency_conflict", "analysis_request_id was already used with a different request")
                return existing.result_payload
            session.add(self._row(request, result))
        return result

    def get(self, analysis_id: str) -> dict[str, Any] | None:
        with self.sessions() as session:
            row = session.get(AnalysisRow, analysis_id)
            return row.result_payload if row and row.expires_at > datetime.now(UTC) else None

    def update(self, result: dict[str, Any]) -> dict[str, Any]:
        """Commit a lifecycle transition before the result is returned to pollers."""
        with self.sessions.begin() as session:
            row = session.get(AnalysisRow, result["analysis_id"])
            if row is None:
                raise AnalysisError("result_not_found", "Analysis result does not exist", "not_found")
            row.status = result["status"]
            row.result_payload = result
        return result

    def get_by_request(self, request_id: str, study_id: str) -> dict[str, Any] | None:
        with self.sessions() as session:
            row = session.scalar(select(AnalysisRow).where(
                AnalysisRow.analysis_request_id == request_id, AnalysisRow.study_id == study_id,
            ))
            return row.result_payload if row and row.expires_at > datetime.now(UTC) else None

    def list_page(self, study_id: str, limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
        limit = max(1, min(int(limit), 100))
        statement = select(AnalysisRow).where(
            AnalysisRow.study_id == study_id,
            AnalysisRow.expires_at > datetime.now(UTC),
        )
        if cursor:
            try:
                stamp, analysis_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("\0", 1)
                created = datetime.fromisoformat(stamp)
                uuid.UUID(analysis_id)
            except (ValueError, UnicodeError, TypeError) as exc:
                raise AnalysisError("invalid_cursor", "cursor is malformed") from exc
            statement = statement.where(
                (AnalysisRow.created_at < created)
                | ((AnalysisRow.created_at == created) & (AnalysisRow.analysis_id < analysis_id))
            )
        statement = statement.order_by(AnalysisRow.created_at.desc(), AnalysisRow.analysis_id.desc()).limit(limit + 1)
        with self.sessions() as session:
            rows = list(session.scalars(statement))
        more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = None
        if more and rows:
            stamp = rows[-1].created_at.isoformat().replace("+00:00", "Z")
            next_cursor = base64.urlsafe_b64encode(f"{stamp}\0{rows[-1].analysis_id}".encode()).decode()
        return {"results": [row.result_payload for row in rows], "next_cursor": next_cursor, "limit": limit}

    def purge_expired(self, *, now: datetime | None = None) -> int:
        """Delete expired results; invoke from the integrator's scheduled retention job."""
        from sqlalchemy import delete

        with self.sessions.begin() as session:
            result = session.execute(delete(AnalysisRow).where(AnalysisRow.expires_at <= (now or datetime.now(UTC))))
            return int(result.rowcount or 0)
