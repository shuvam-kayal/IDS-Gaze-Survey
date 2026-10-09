# Frozen four-person ownership model

P1 owns participant browser runtime, invitation, consent, camera permission lifecycle, trials, surveys, interaction collection, AOI geometry and event buffering. P2 owns researcher console, auth/roles, Experiences, multiple Studies per Experience, eligibility, AOI/question authoring and versioned configuration. P3 owns ingestion/persistence, external gaze adapter, canonical GazeRecord, calibration/quality, fixation/AOI mapping, TTFF/dwell/revisits/transitions/entropy/scan-path features and non-gaze feature extraction. P4 owns statistics, ML, evaluation, modality-aware and non-gaze fallback models, results, heatmaps, reports and recommendations.

P3 begins with synthetic event fixtures; P4 begins immediately with synthetic FeatureRecords. P1 owns camera permission/capture UX, P3 owns gaze estimator integration. P2 configures and versions AOIs; P1 resolves live geometry; P3 maps gaze to AOIs. Shared contracts require affected-owner review.
