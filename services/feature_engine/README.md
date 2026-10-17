# P3 — Feature engine

Own reusable feature computation, AOI mapping, fixation metrics, non-gaze metrics and FeatureRecord provenance. Missing gaze is missing, not zero. Keep feature names, units, windows, AOI version and feature_set_version stable and documented.

Slice V metrics are implemented in `gaze_metrics.py` using the
`trial.exposure_started` event and study-scoped GeometrySnapshot v2 context.
The baseline uses `gaze-baseline-1`: TTFF is measured in milliseconds from the
event occurrence to the first qualifying fixation in the requested AOI; dwell
is the sum of qualifying fixation durations only; revisits include returns
after another resolved AOI or an unresolved interval; transitions use
consecutive resolved AOIs; entropy is base-2 Shannon entropy over resolved
fixation dwell shares; and scan paths preserve unresolved observations while
collapsing consecutive duplicates. Metric values are nullable objects with
units, window, AOI-set version, algorithm version, and reason codes. Numeric
zero is reserved for a measured zero.

The M2b orchestration entry point is `gaze_pipeline.process_trial_gaze`. It
requires a validated `TrialObservationContext`, keeps provider samples behind
the existing adapter, validates the explicit association before fixation
detection, pins AOI mapping to the requested study and AOI-set version, and
builds the existing FeatureRecord. It does not persist raw video or invent
gaze values when capture is unavailable.

For M3 sessions, `process_session_gaze` validates the existing bootstrap's
eligible-study assignments and invokes that trial pipeline independently for
each study. It filters shared EventEnvelope inputs by `study_ids` and never
selects an unpinned configuration or AOI-set version.

The M4 repository bridge is `process_persisted_session_gaze`. It reads
validated EventEnvelopes through the existing telemetry repository and passes
them to the M3 coordinator; provider samples remain structured, consented
inputs to the adapter and raw video is neither accepted nor persisted. This is
the P3 processing boundary, not a browser runtime or API endpoint.
