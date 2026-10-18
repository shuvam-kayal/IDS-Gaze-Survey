"""Durable P3 telemetry persistence using the frozen PostgreSQL stack."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    delete,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from services.telemetry.ingestion import _parse_utc_timestamp, validate_event


def utc_now() -> datetime:
    return datetime.now(UTC)


def canonical_event(event: dict[str, Any]) -> str:
    return json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def event_fingerprint(event: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_event(event).encode("utf-8")).hexdigest()


class Base(DeclarativeBase):
    pass


class TelemetryEvent(Base):
    __tablename__ = "telemetry_events"
    __table_args__ = (
        UniqueConstraint("session_id", "event_id", name="uq_telemetry_event_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    experience_id: Mapped[str] = mapped_column(String(255), nullable=False)
    participant_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_type: Mapped[str] = mapped_column(String(255), nullable=False)
    study_ids: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)


class SessionProcessing(Base):
    __tablename__ = "telemetry_session_processing"

    session_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


@dataclass(frozen=True)
class IngestionResult:
    event_id: str
    duplicate: bool
    ingested_at: datetime


class IdentityConflict(ValueError):
    """The same session/event identity was reused with different content."""


class TelemetryRepository:
    def __init__(self, engine: Engine):
        self.engine = engine
        self.sessions = sessionmaker(bind=engine, expire_on_commit=False)

    @classmethod
    def from_env(cls) -> TelemetryRepository:
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL is required for durable telemetry persistence")
        return cls(create_engine(url, pool_pre_ping=True))

    def ingest(self, event: dict[str, Any]) -> IngestionResult:
        validate_event(event)
        fingerprint = event_fingerprint(event)
        occurred_at = _parse_utc_timestamp(event["occurred_at"])
        with self.sessions.begin() as db:
            statement = insert(TelemetryEvent).values(
                session_id=event["session_id"],
                event_id=event["event_id"],
                schema_version=event["schema_version"],
                experience_id=event["experience_id"],
                participant_id=event.get("participant_id"),
                event_type=event["event_type"],
                study_ids=event["study_ids"],
                payload=event["payload"],
                occurred_at=occurred_at,
                ingested_at=utc_now(),
                fingerprint=fingerprint,
            )
            inserted_row = db.execute(
                statement.on_conflict_do_nothing(
                    index_elements=["session_id", "event_id"]
                ).returning(TelemetryEvent.event_id, TelemetryEvent.ingested_at)
            ).first()
            if inserted_row is not None:
                inserted_event_id, ingested_at = inserted_row
                processing = db.get(SessionProcessing, event["session_id"])
                if processing is None:
                    db.add(
                        SessionProcessing(
                            session_id=event["session_id"],
                            state="open",
                            updated_at=ingested_at,
                        )
                    )
                elif processing.state == "complete":
                    processing.state = "open"
                    processing.updated_at = ingested_at
                return IngestionResult(inserted_event_id, False, ingested_at)

            existing = db.scalar(
                select(TelemetryEvent).where(
                    TelemetryEvent.session_id == event["session_id"],
                    TelemetryEvent.event_id == event["event_id"],
                )
            )
            if existing is None:
                raise RuntimeError("telemetry event disappeared during ingestion")
            if existing.fingerprint != fingerprint:
                raise IdentityConflict(f"event identity conflict for {event['event_id']!r}")
            return IngestionResult(existing.event_id, True, existing.ingested_at)

    def list_events(self, session_id: str, *, study_id: str | None = None) -> list[dict[str, Any]]:
        with self.sessions() as db:
            rows = db.scalars(
                select(TelemetryEvent)
                .where(TelemetryEvent.session_id == session_id)
                .order_by(
                    TelemetryEvent.occurred_at, TelemetryEvent.ingested_at, TelemetryEvent.event_id
                )
            ).all()
            result = []
            for row in rows:
                if study_id is not None and study_id not in row.study_ids:
                    continue
                result.append(
                    {
                        "schema_version": row.schema_version,
                        "event_id": row.event_id,
                        "experience_id": row.experience_id,
                        "study_ids": row.study_ids,
                        "session_id": row.session_id,
                        "participant_id": row.participant_id,
                        "event_type": row.event_type,
                        "occurred_at": row.occurred_at.astimezone(UTC)
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "payload": row.payload,
                        "ingested_at": row.ingested_at.astimezone(UTC)
                        .isoformat()
                        .replace("+00:00", "Z"),
                    }
                )
            return result

    def mark_session_closed(self, session_id: str, *, partial: bool = False) -> None:
        now = utc_now()
        state = "partial" if partial else "finalizing"
        with self.sessions.begin() as db:
            processing = db.get(SessionProcessing, session_id)
            if processing is None:
                db.add(
                    SessionProcessing(
                        session_id=session_id, state=state, closed_at=now, updated_at=now
                    )
                )
            else:
                processing.state, processing.closed_at, processing.updated_at = state, now, now

    def mark_complete(self, session_id: str) -> None:
        with self.sessions.begin() as db:
            processing = db.get(SessionProcessing, session_id)
            if processing is None:
                raise ValueError(f"unknown session: {session_id}")
            processing.state, processing.updated_at = "complete", utc_now()

    def delete_session(self, session_id: str) -> bool:
        with self.sessions.begin() as db:
            deleted = db.query(TelemetryEvent).filter_by(session_id=session_id).delete()
            db.query(SessionProcessing).filter_by(session_id=session_id).delete()
            return bool(deleted)

    def purge_expired_events(self, *, now: datetime | None = None, retention_days: int = 30) -> int:
        if not isinstance(retention_days, int) or isinstance(retention_days, bool):
            raise TypeError("retention_days must be an integer")
        if retention_days <= 0:
            raise ValueError("retention_days must be positive")
        reference_time = now or utc_now()
        if reference_time.tzinfo is None or reference_time.utcoffset() != UTC.utcoffset(None):
            raise ValueError("now must be timezone-aware UTC")
        cutoff = reference_time.astimezone(UTC) - timedelta(days=retention_days)
        with self.sessions.begin() as db:
            expired_sessions = (
                select(SessionProcessing.session_id)
                .where(
                    SessionProcessing.closed_at.is_not(None),
                    SessionProcessing.closed_at < cutoff,
                )
            )
            result = db.execute(
                delete(TelemetryEvent).where(
                    TelemetryEvent.session_id.in_(expired_sessions)
                )
            )
            return result.rowcount or 0
