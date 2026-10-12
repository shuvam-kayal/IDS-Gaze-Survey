# Database ownership

The selected persistence architecture is PostgreSQL 16 with SQLAlchemy 2.x,
psycopg 3, and Alembic. Cross-workstream decisions are frozen in
[`architecture/INTEGRATION_FREEZE.md`](../architecture/INTEGRATION_FREEZE.md).

P2 owns users/roles, Experiences, Studies, eligibility and immutable AOI/
question config versions. P3 owns events, ingestion metadata, canonical gaze
records subject to retention, FeatureRecords and quality metadata. P4 owns
analysis requests, model/evaluation metadata, AnalysisResults and reports. P1
owns the transient unsent event queue and trial state; raw camera frames are
not persisted by default.

Use Alembic migrations and repository interfaces. P3 owns telemetry model
requirements; the integrator owns the shared migration path and API wiring.
Retention and deletion propagate across raw events, gaze records, derived
features, caches and results according to the operational defaults in the
integration freeze. Avoid direct identifiers unless justified and consented.
