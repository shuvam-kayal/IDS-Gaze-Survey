# P4 analytics integration proposal

Status: proposal for integrator/P2/P3 review. No frozen shared contract, P3 implementation, shared API shell, or shared Alembic migration is changed by this proposal.

## Frozen contract boundary

- Continue accepting exactly `contracts/schemas/analysis-request.v1.schema.json` at the top level and emit exactly `contracts/schemas/analysis-result.v1.schema.json` at the top level.
- P4-only analysis types are carried in the existing open `parameters` object as `p4_extension: {"schema_version":"1.0.0","analysis_types":[...]}`. This is a versioned P4 extension schema, not a redefinition of v1. Confirm this extension convention with the contract owner before cross-person use.
- The v1 result's `results` object holds P4 analyses and `p4_provenance`; P4 metadata is not added as undeclared top-level fields.

## FeatureRecord and heatmap boundary

- P4 consumes canonical FeatureRecord v1 records from a P3-owned internal provider. The adapter maps `feature_record_id` to the engine's internal record key and preserves `session_id`, canonical modality, `quality.missingness`, metric units, and `requested_aoi_id`.
- FeatureRecord v1 has no `participant_id`, `spatial`, or numeric gaze-quality score. P4 groups only by the available canonical `session_id`; it reports missing quality-score availability and never creates a substitute score.
- Heatmaps use an optional P4 `HeatmapInput` v1 payload from a separately authorized provider. It carries `study_id`, `feature_record_id`, `session_id`, `geometry_snapshot_id`, coordinate points, coordinate system, observed quality, and AOI geometry/version. The integration owner/P3 must agree which internal repository can safely supply these values and enforce study scope/deletion before enabling the provider.

## API and UI integration

- P4 exports `create_analytics_router(...)` for `services/api/app.py` to include after authentication and route review. P4 does not modify shared API wiring. Its job routes return queued/running/terminal frozen AnalysisResult v1 responses; the integrator should bind lifecycle execution to the shared durable queue before multi-process deployment.
- The router injects the P3 FeatureRecord provider, PostgreSQL result repository, and P2/integrator study authorizer. It does not accept client-supplied FeatureRecords.
- The researcher console consumes `apps/researcher-console/src/features/analytics/client.ts`; the P2 console owner imports this feature into the shared navigation/shell.

## PostgreSQL and Alembic proposal

P4 proposes table `p4_analysis_results` with primary key `analysis_id`; unique `(analysis_request_id, study_id)` idempotency; `study_id`, `feature_set_version`, lifecycle `status`, `created_at`, `expires_at`, and JSONB `request_payload`/`result_payload`; plus an index on `(study_id, created_at, analysis_id)`. Results expire 90 days after creation and `AnalysisRepository.purge_expired()` is intended for the shared retention scheduler. Deletion/withdrawal must remove linked P4 rows when upstream scope is deleted.

The shared Alembic environment currently targets P3 telemetry metadata and migration execution is integrator-owned. Before adding a revision, agree whether the integrator will compose P4 `AnalysisRow` metadata into the shared migration environment or author an explicit migration revision with the P4 owner. No migration is included until that decision is approved.

## Current P4 implementation boundary

The feature router and repository are ready for dependency injection, but a real database integration requires the accepted migration, shared DB session configuration, the P3 retrieval provider, P2 authorization, and optional heatmap provider. This proposal records those handoffs without claiming the cross-person integration is complete.
