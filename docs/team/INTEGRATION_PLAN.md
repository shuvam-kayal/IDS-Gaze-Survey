# Integration plan

M0: agree contracts, IDs, timestamps, missingness and modality. M1: P1 emits synthetic events, P2 configures an Experience/Study, P3 emits non-gaze FeatureRecords from fixtures, P4 emits AnalysisResults from fixtures. M2: consented gaze path, adapter, quality and AOI mapping. M3: multi-study eligibility, survey consolidation and config pinning. M4: browser-to-result end-to-end journey including denied/interrupted camera. M5: access control, retention/deletion, accessibility, performance and deployment hardening.

Integration is complete only when contract tests pass, retries are idempotent, outputs are versioned, fallback works, tests cover multi-study/AOI/missingness, results show modality/limitations and CI passes.
