# Data dictionary

The canonical identifiers, relationships, timestamp rules, duplicate scope,
and missingness codes are frozen in
[`architecture/INTEGRATION_FREEZE.md`](../architecture/INTEGRATION_FREEZE.md).

`experience_id` identifies the website/product experience. `study_ids`
represents the study context assigned to an event. `session_id` identifies one
browser session, not a verified real-world identity. `participant_id` is
optional and pseudonymous. `event_id` is stable for retry deduplication within
the `(session_id, event_id)` identity. `occurred_at` is UTC RFC 3339;
persisted records also carry server `ingested_at`. `modality` is
`gaze_and_non_gaze` or `non_gaze_only`. Feature names document units and
feature-set version. `quality.missingness` contains reason codes; AOI identity
and AOI config version are retained for reproducibility.
