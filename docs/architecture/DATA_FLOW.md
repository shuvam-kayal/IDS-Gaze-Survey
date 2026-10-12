# Data flow

The exact IDs, persistence states, duplicate semantics, ordering, and deletion
rules are frozen in
[`INTEGRATION_FREEZE.md`](INTEGRATION_FREEZE.md).

1. P2 configures an Experience and versioned Studies.
2. The bootstrap service creates a pseudonymous session after consent and
   returns eligible, version-pinned Studies.
3. P1 presents consent and camera status. Camera starts only after explicit
   research consent and separate browser permission.
4. P1 emits versioned EventEnvelope events with stable IDs.
5. P3 validates, deduplicates by `(session_id, event_id)`, persists the event
   with server `ingested_at`, and normalizes gaze through the provider boundary
   when available.
6. P3 emits reusable FeatureRecords; camera-denied sessions use
   `non_gaze_only` with reason-coded missingness.
7. P4 runs compatible analysis and emits versioned AnalysisResults with
   modality and limitations.
8. P2 displays results with sample size and quality metadata.

Use UTC RFC 3339 timestamps; distinguish event occurrence from ingestion time. Retries preserve event IDs. Avoid sensitive payloads in logs.
