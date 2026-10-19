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
    Boolean,
    DateTime,
    Float,
    ForeignKeyConstraint,
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


class GazeRecordRow(Base):
    __tablename__ = "gaze_records"
    __table_args__ = (
        UniqueConstraint("session_id", "sample_id", name="uq_gaze_record_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    sample_id: Mapped[str] = mapped_column(String(255), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    coordinate_space: Mapped[str] = mapped_column(String(64), nullable=False)
    x_normalized: Mapped[float | None] = mapped_column(Float, nullable=True)
    y_normalized: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    calibration_status: Mapped[str] = mapped_column(String(32), nullable=False)
    quality_flags: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)


class GazeObservationAssociationRow(Base):
    __tablename__ = "gaze_observation_associations"

    association_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    study_id: Mapped[str] = mapped_column(String(255), nullable=False)
    trial_id: Mapped[str] = mapped_column(String(255), nullable=False)
    aoi_set_version: Mapped[str] = mapped_column(String(255), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)


class GazeObservationAssociationRecordRow(Base):
    __tablename__ = "gaze_observation_association_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["association_id", "session_id"],
            [
                "gaze_observation_associations.association_id",
                "gaze_observation_associations.session_id",
            ],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["session_id", "sample_id"],
            ["gaze_records.session_id", "gaze_records.sample_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "association_id", "session_id", "sample_id",
            name="uq_gaze_association_record",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    association_id: Mapped[str] = mapped_column(String(255), nullable=False)
    session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    sample_id: Mapped[str] = mapped_column(String(255), nullable=False)


class FeatureRecordRow(Base):
    __tablename__ = "feature_records"

    feature_record_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    experience_id: Mapped[str] = mapped_column(String(255), nullable=False)
    study_id: Mapped[str] = mapped_column(String(255), nullable=False)
    session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    feature_set_version: Mapped[str] = mapped_column(String(64), nullable=False)
    config_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    aoi_set_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    modality: Mapped[str] = mapped_column(String(64), nullable=False)
    window: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
    features: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    quality: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    source_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


@dataclass(frozen=True)
class IngestionResult:
    event_id: str
    duplicate: bool
    ingested_at: datetime


class IdentityConflict(ValueError):
    """The same session/event identity was reused with different content."""


class RecordIdentityConflict(ValueError):
    """A durable derived-record identity was reused with different content."""


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

    @staticmethod
    def _record_fingerprint(record: dict[str, Any]) -> str:
        return hashlib.sha256(canonical_event(record).encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_gaze_record(record: dict[str, Any]) -> None:
        required = {
            "schema_version", "sample_id", "session_id", "occurred_at",
            "coordinate_space", "x_normalized", "y_normalized", "confidence",
            "valid", "calibration_status", "quality_flags",
        }
        if not isinstance(record, dict) or set(record) != required:
            raise ValueError("gaze record must match the canonical v1 fields")
        if record["schema_version"] != "1.0.0":
            raise ValueError("unsupported GazeRecord schema_version")
        for field in ("sample_id", "session_id", "coordinate_space", "calibration_status"):
            if not isinstance(record[field], str) or not record[field]:
                raise ValueError(f"{field} must be a non-empty string")
        if record["coordinate_space"] != "viewport_normalized":
            raise ValueError("unsupported GazeRecord coordinate_space")
        _parse_utc_timestamp(record["occurred_at"])
        if not isinstance(record["valid"], bool) or not isinstance(record["quality_flags"], list):
            raise TypeError("invalid GazeRecord validity or quality fields")

    @staticmethod
    def _validate_feature_record(record: dict[str, Any]) -> None:
        required = {
            "schema_version", "feature_record_id", "experience_id", "study_id",
            "session_id", "feature_set_version", "config_version", "aoi_set_version",
            "modality", "window", "features", "quality", "source_event_count",
        }
        if not isinstance(record, dict) or set(record) != required:
            raise ValueError("feature record must match the canonical v1 fields")
        if record["schema_version"] != "1.0.0":
            raise ValueError("unsupported FeatureRecord schema_version")
        for field in ("feature_record_id", "experience_id", "study_id", "session_id", "feature_set_version"):
            if not isinstance(record[field], str) or not record[field]:
                raise ValueError(f"{field} must be a non-empty string")
        if record["modality"] not in {"gaze_and_non_gaze", "non_gaze_only"}:
            raise ValueError("unsupported FeatureRecord modality")
        if not isinstance(record["features"], dict) or not isinstance(record["quality"], dict):
            raise TypeError("FeatureRecord features and quality must be objects")
        if not isinstance(record["source_event_count"], int) or record["source_event_count"] < 0:
            raise ValueError("source_event_count must be a non-negative integer")

    def persist_gaze_association(
        self, association: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Persist canonical gaze records and their study/trial association.

        Exact retries are no-ops. Reusing a sample or association identity with
        different content raises ``RecordIdentityConflict`` inside the same
        transaction.
        """
        required = {
            "schema_version", "association_id", "session_id", "study_id", "trial_id",
            "aoi_set_version", "window_start", "window_end", "gaze_records",
        }
        if not isinstance(association, dict) or set(association) != required:
            raise ValueError("gaze observation association has invalid fields")
        records = association["gaze_records"]
        if not isinstance(records, list):
            raise TypeError("gaze_records must be an array")
        for record in records:
            self._validate_gaze_record(record)
            if record["session_id"] != association["session_id"]:
                raise ValueError("gaze record session_id does not match association")
        start = _parse_utc_timestamp(association["window_start"])
        end = _parse_utc_timestamp(association["window_end"])
        if end <= start:
            raise ValueError("association window_end must be after window_start")
        association_fingerprint = self._record_fingerprint(association)
        with self.sessions.begin() as db:
            existing_association = db.get(
                GazeObservationAssociationRow,
                (association["association_id"], association["session_id"]),
            )
            if existing_association is not None:
                if existing_association.fingerprint != association_fingerprint:
                    raise RecordIdentityConflict("gaze association identity conflict")
            else:
                db.add(
                    GazeObservationAssociationRow(
                        association_id=association["association_id"],
                        session_id=association["session_id"],
                        study_id=association["study_id"],
                        trial_id=association["trial_id"],
                        aoi_set_version=association["aoi_set_version"],
                        window_start=start,
                        window_end=end,
                        fingerprint=association_fingerprint,
                    )
                )
            for record in records:
                fingerprint = self._record_fingerprint(record)
                existing = db.scalar(
                    select(GazeRecordRow).where(
                        GazeRecordRow.session_id == record["session_id"],
                        GazeRecordRow.sample_id == record["sample_id"],
                    )
                )
                if existing is not None:
                    if existing.fingerprint != fingerprint:
                        raise RecordIdentityConflict("gaze sample identity conflict")
                else:
                    db.add(
                        GazeRecordRow(
                            session_id=record["session_id"],
                            sample_id=record["sample_id"],
                            schema_version=record["schema_version"],
                            occurred_at=_parse_utc_timestamp(record["occurred_at"]),
                            coordinate_space=record["coordinate_space"],
                            x_normalized=record["x_normalized"],
                            y_normalized=record["y_normalized"],
                            confidence=record["confidence"],
                            valid=record["valid"],
                            calibration_status=record["calibration_status"],
                            quality_flags=record["quality_flags"],
                            fingerprint=fingerprint,
                        )
                    )
                link = db.scalar(
                    select(GazeObservationAssociationRecordRow).where(
                        GazeObservationAssociationRecordRow.association_id == association["association_id"],
                        GazeObservationAssociationRecordRow.session_id == record["session_id"],
                        GazeObservationAssociationRecordRow.sample_id == record["sample_id"],
                    )
                )
                if link is None:
                    db.add(
                        GazeObservationAssociationRecordRow(
                            association_id=association["association_id"],
                            session_id=record["session_id"],
                            sample_id=record["sample_id"],
                        )
                    )
        return records

    def list_gaze_records(self, session_id: str) -> list[dict[str, Any]]:
        with self.sessions() as db:
            rows = db.scalars(
                select(GazeRecordRow)
                .where(GazeRecordRow.session_id == session_id)
                .order_by(GazeRecordRow.occurred_at, GazeRecordRow.sample_id)
            ).all()
            return [
                {
                    "schema_version": row.schema_version,
                    "sample_id": row.sample_id,
                    "session_id": row.session_id,
                    "occurred_at": row.occurred_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                    "coordinate_space": row.coordinate_space,
                    "x_normalized": row.x_normalized,
                    "y_normalized": row.y_normalized,
                    "confidence": row.confidence,
                    "valid": row.valid,
                    "calibration_status": row.calibration_status,
                    "quality_flags": row.quality_flags,
                }
                for row in rows
            ]

    def persist_feature_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """Persist one schema-valid FeatureRecord with exact-retry semantics."""
        self._validate_feature_record(record)
        fingerprint = self._record_fingerprint(record)
        with self.sessions.begin() as db:
            existing = db.get(FeatureRecordRow, record["feature_record_id"])
            if existing is not None:
                if existing.fingerprint != fingerprint:
                    raise RecordIdentityConflict("feature record identity conflict")
                return record
            db.add(
                FeatureRecordRow(
                    feature_record_id=record["feature_record_id"],
                    experience_id=record["experience_id"],
                    study_id=record["study_id"],
                    session_id=record["session_id"],
                    feature_set_version=record["feature_set_version"],
                    config_version=record["config_version"],
                    aoi_set_version=record["aoi_set_version"],
                    modality=record["modality"],
                    window=record["window"],
                    features=record["features"],
                    quality=record["quality"],
                    source_event_count=record["source_event_count"],
                    fingerprint=fingerprint,
                    created_at=utc_now(),
                )
            )
        return record

    def gaze_association_exists(self, association_id: str, session_id: str) -> bool:
        with self.sessions() as db:
            return db.get(
                GazeObservationAssociationRow, (association_id, session_id)
            ) is not None

    def feature_record_exists(self, feature_record_id: str) -> bool:
        with self.sessions() as db:
            return db.get(FeatureRecordRow, feature_record_id) is not None

    def list_feature_records(self, session_id: str, *, study_id: str | None = None) -> list[dict[str, Any]]:
        with self.sessions() as db:
            statement = select(FeatureRecordRow).where(FeatureRecordRow.session_id == session_id)
            if study_id is not None:
                statement = statement.where(FeatureRecordRow.study_id == study_id)
            rows = db.scalars(
                statement.order_by(FeatureRecordRow.created_at, FeatureRecordRow.feature_record_id)
            ).all()
            return [
                {
                    "schema_version": "1.0.0",
                    "feature_record_id": row.feature_record_id,
                    "experience_id": row.experience_id,
                    "study_id": row.study_id,
                    "session_id": row.session_id,
                    "feature_set_version": row.feature_set_version,
                    "config_version": row.config_version,
                    "aoi_set_version": row.aoi_set_version,
                    "modality": row.modality,
                    "window": row.window,
                    "features": row.features,
                    "quality": row.quality,
                    "source_event_count": row.source_event_count,
                }
                for row in rows
            ]

    def delete_session(self, session_id: str) -> bool:
        """Delete all currently persisted P3 state for one session.

        It is idempotent and reports whether any supported P3 row existed.
        """
        with self.sessions.begin() as db:
            deleted_features = db.query(FeatureRecordRow).filter_by(
                session_id=session_id
            ).delete(synchronize_session=False)
            deleted_association_records = db.query(GazeObservationAssociationRecordRow).filter_by(
                session_id=session_id
            ).delete(synchronize_session=False)
            deleted_associations = db.query(GazeObservationAssociationRow).filter_by(
                session_id=session_id
            ).delete(synchronize_session=False)
            deleted_gaze_records = db.query(GazeRecordRow).filter_by(
                session_id=session_id
            ).delete(synchronize_session=False)
            deleted_events = (
                db.query(TelemetryEvent)
                .filter_by(session_id=session_id)
                .delete(synchronize_session=False)
            )
            deleted_processing = (
                db.query(SessionProcessing)
                .filter_by(session_id=session_id)
                .delete(synchronize_session=False)
            )
            return bool(
                deleted_features
                or deleted_association_records
                or deleted_associations
                or deleted_gaze_records
                or deleted_events
                or deleted_processing
            )

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
            event_result = db.execute(
                delete(TelemetryEvent).where(
                    TelemetryEvent.session_id.in_(expired_sessions)
                )
            )
            # Retention must remove the processing/idempotency state together
            # with the expired raw events. Keep the return value as the number
            # of expired events for compatibility with the existing method.
            db.execute(
                delete(SessionProcessing).where(
                    SessionProcessing.session_id.in_(expired_sessions)
                )
            )
            return event_result.rowcount or 0
