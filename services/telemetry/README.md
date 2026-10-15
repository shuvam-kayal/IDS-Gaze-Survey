# P3 — Telemetry ingestion

Owns EventEnvelope validation, idempotency, server ingestion timestamps,
PostgreSQL storage, retention and event-to-feature handoff. The M2a slice adds
the `TelemetryRepository` and Alembic-backed event/session tables; gaze and
derived FeatureRecord persistence remain later milestones.
