# Data flow

1. P2 configures Experience and versioned Studies. 2. P1 receives session bootstrap and presents invitation/consent. 3. Camera starts only after explicit research consent and separate browser permission. 4. P1 emits versioned EventEnvelope events with stable IDs. 5. P3 validates/deduplicates, persists telemetry and normalizes gaze through the adapter. 6. P3 emits reusable FeatureRecords. 7. P4 runs compatible analysis and emits versioned AnalysisResults with modality and limitations. 8. P2 displays results with sample size and quality metadata.

Use UTC RFC 3339 timestamps; distinguish event occurrence from ingestion time. Retries preserve event IDs. Avoid sensitive payloads in logs.
