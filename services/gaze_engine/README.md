# P3 — Gaze adapter

Implement provider-specific integration behind GazeProviderAdapter. Convert provider output into contracts/schemas/gaze-record.v1.schema.json. Keep provider-specific keys, units and objects inside this adapter. Add calibration, quality flags, missingness reasons and synthetic provider fixtures. Do not store raw camera frames by default.

The provider-neutral quality boundary is implemented in `quality.py`. It accepts
only canonical `GazeRecord` dictionaries and reports an internal assessment; it
does not add fields to the frozen `GazeRecord` or `FeatureRecord` contracts and
does not claim calibrated accuracy. A session is `usable` only when it has at
least three valid samples, at least half of its samples are valid, and the mean
confidence is at least `0.5`, with confidence present on every valid sample.
These thresholds are inclusive. Missing coordinates or invalid samples are never
repaired, and missing confidence is explicitly reported as low quality. Empty
input is `no_samples`; non-empty input without usable samples is
`insufficient_data`.
