# Database ownership

Logical domains need not be separate physical databases initially. P2 owns users/roles, Experiences, Studies, eligibility and immutable AOI/question config versions. P3 owns events, ingestion metadata, canonical gaze records subject to retention, FeatureRecords and quality metadata. P4 owns analysis requests, model/evaluation metadata, AnalysisResults and reports. P1 owns transient unsent event queue and trial state; do not persist camera frames by default.

Use migrations and repository interfaces. Define retention/deletion propagation across raw events, gaze records, derived features, caches and results before real collection. Avoid direct identifiers unless justified and consented.
