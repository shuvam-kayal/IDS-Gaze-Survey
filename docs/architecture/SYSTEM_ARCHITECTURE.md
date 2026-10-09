# System architecture

P1 owns the participant browser SDK/runtime, invitation, consent, camera lifecycle, trials, surveys, interaction events, dynamic AOI geometry and event buffering. P2 owns researcher console, auth/roles, Experiences, multiple Studies per Experience, eligibility, AOI/question authoring and versioned configuration. P3 owns event ingestion/persistence, external gaze adapter, canonical GazeRecord, calibration/quality, fixation/AOI mapping, gaze and non-gaze features and FeatureRecord store. P4 owns statistics, ML, modality-aware evaluation, AnalysisResult, heatmaps, reports and recommendations.

One Experience may contain multiple Studies. Studies may define distinct AOI/question sets, eligibility and survey timing. A session may qualify for multiple Studies; assignment and question consolidation must be deterministic and versioned. AOIs are configured by researchers but resolved against live DOM geometry. External gaze formats never cross the P3 adapter.

This is a scaffold, not a production-ready platform. The current event endpoint validates but does not persist. Authentication, migrations, consent audit storage, camera capture, gaze estimation, feature computation, models and dashboards remain implementation work.
