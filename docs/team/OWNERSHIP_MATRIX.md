# Ownership and parallel development

P1: participant browser SDK, invitation, consent, camera lifecycle, trial/survey runtime, interactions, dynamic AOI geometry, event envelope and retries. P2: researcher console, roles, Experience/Study config, eligibility/assignment, AOI/questions, timing and config APIs. P3: ingestion/storage, external gaze adapter, canonical GazeRecord, quality/calibration, fixation/AOI mapping, TTFF/dwell/revisit/transition/entropy/scan-path and non-gaze features. P4: statistics, ML, evaluation, fallback models, results, heatmaps, reports and recommendations.

Use short-lived owner branches and draft PRs. Freeze schemas/examples before independent work. P3 begins with synthetic events; P4 starts immediately with synthetic FeatureRecords. Shared contracts, root manifests, CI, Compose and migrations require integrator coordination. Cross-boundary PRs name affected owners and update tests/examples. Never commit secrets or identifiable participant/camera data.
