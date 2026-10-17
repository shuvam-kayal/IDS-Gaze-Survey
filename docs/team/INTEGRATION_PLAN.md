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
