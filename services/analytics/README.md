# Person 4 analytics integration

This package owns statistical analysis, evaluation, reports, and AnalysisResult creation. The shared API mounts `create_analytics_router(...)` from `services.analytics.integration` under `/v1/analytics`; P4 does not start a separate HTTP server.

## Runtime requirements

- Python 3.11 or newer
- PostgreSQL 16, through the shared `DATABASE_URL`
- SQLAlchemy 2.x, psycopg 3, and the repository Alembic setup

Install the repository dependencies with `python -m pip install -e '.[dev]'`. Configure `DATABASE_URL` using the shared local development setup, then apply the agreed Alembic migration through the project's migration workflow. The analytics repository intentionally refuses SQLite.

## Shared API wiring

The shared API injects these dependencies when calling `create_analytics_router`:

- `get_feature_provider`: provides `TelemetryFeatureRecordProvider` over P3 telemetry. The control plane supplies only sessions assigned to the requested study with accepted research consent and without withdrawal; the adapter reads P3 `list_feature_records(session_id, study_id=...)` and filters the requested feature-set version.
- `get_repository`: returns a configured `AnalysisRepository` bound to the shared PostgreSQL database.
- `get_study_authorizer`: checks researcher study-view permission and verifies the requested `study_id` exists.
- `get_export_authorizer`: checks the separate results-export permission for CSV downloads.
- `get_heatmap_provider` (optional): separately authorized coordinate/geometry retrieval; it must return P4 HeatmapInput v1 payloads keyed by canonical `feature_record_id`.

Routes are under `/v1/analytics`: `GET /models`, `GET /feature-sets`, `POST /analyze`, `POST /jobs`, `GET /jobs/{analysis_id}`, `GET /results/{analysis_id}`, `GET /results`, `GET /compare`, and aggregate-only `GET /results/{analysis_id}/csv`. Job lifecycle responses use frozen AnalysisResult v1 statuses; replace FastAPI in-process background execution with a durable worker before multi-process deployment. Requests use the frozen AnalysisRequest v1 object. The package maps it to the frozen AnalysisResult v1 object. Additional P4 analysis modules are requested only through the explicitly versioned `parameters.p4_extension` object described by `contracts/analysis-extension.v1.schema.json`.

The canonical P3 FeatureRecord v1 adapter preserves `feature_record_id`, `session_id`, modality, quality missingness codes, and `requested_aoi_id`; it does not invent participant IDs or numerical gaze quality. FeatureRecord v1 does not contain `spatial`. Heatmaps consume the separate `services/analytics/heatmap-input.v1.schema.json` shape returned by the injected provider and validate matching study/record/session identity plus geometry snapshot reference.

## Persistence and migration boundary

`AnalysisRepository` uses SQLAlchemy 2.x and PostgreSQL JSONB under `DATABASE_URL`, with idempotency on `(analysis_request_id, study_id)` and a 90-day expiry timestamp. Migration `20261021_0007` creates the P4 results table. Call `purge_expired()` from a retention scheduler; no scheduler is currently included.

## Research safeguards

Unavailable gaze stays missing and is never imputed as zero. FeatureRecord v1 has reason-coded missingness but no per-feature numerical quality score; the adapter reports this boundary instead of fabricating scores. Results describe associations and exploratory patterns and do not infer cognitive ground truth. Synthetic fixtures are for software checks, not participant evidence.
