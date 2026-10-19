# Integration plan

The cross-workstream decisions for every milestone are frozen in
[`docs/architecture/INTEGRATION_FREEZE.md`](../architecture/INTEGRATION_FREEZE.md).

M0: agree contracts, IDs, timestamps, missingness and modality. M1: P1 emits
synthetic events, P2 configures an Experience/Study, P3 emits non-gaze
FeatureRecords from fixtures, P4 emits AnalysisResults from fixtures. M2a:
PostgreSQL/Alembic persistence and idempotent ingestion. M2b: consented gaze
path, adapter, quality and AOI mapping. M3: multi-study eligibility, survey
consolidation and config pinning. M4: browser-to-result end-to-end journey
including denied/interrupted camera. M5: access control, retention/deletion,
accessibility, performance and deployment hardening.

Integration is complete only when contract tests pass, retries are idempotent, outputs are versioned, fallback works, tests cover multi-study/AOI/missingness, results show modality/limitations and CI passes.

P3 M2b end-to-end acceptance is exercised by
`tests/test_gaze_pipeline.py`: provider samples flow through canonical
normalization, quality, validated trial association, fixation detection,
study/AOI-version-pinned mapping, metrics, and schema-valid FeatureRecord
output. Camera-denied and empty-capture fallback paths are covered. The late
event path reuses the existing persistence behavior that reopens a completed
`SessionProcessing` scope; its PostgreSQL-backed test is skipped when the
configured test database is unavailable.

The P3 M3 slice adds `gaze_pipeline.process_session_gaze`, which validates the
existing SessionBootstrap assignments, sorts and processes one explicit trial
per eligible study, filters EventEnvelope inputs by `study_ids`, and passes
each study's pinned configuration/AOI-set version to the existing single-trial
pipeline. P1 eligibility/lifecycle emission and P2 configuration publication
remain upstream dependencies; this slice does not claim those workstreams are
complete.

The P3 M4 processing slice adds `gaze_pipeline.process_persisted_session_gaze`,
which retrieves already validated EventEnvelopes from the existing telemetry
repository and routes them through the M3 coordinator. The trial path validates
browser-originated EventEnvelope shape, applies batch retry deduplication, and
keeps consented ProviderSample inputs behind the existing adapter; raw camera
frames are not accepted or persisted. Focused pipeline tests cover valid and
invalid events, exact retries, interrupted and denied capture, multi-study
isolation, deterministic reprocessing, and the absence of video data in the
FeatureRecord. A real browser-to-result journey still depends on P1's browser
permission/capture lifecycle and the API/result wiring; this P3 slice does not
claim those components are implemented.
