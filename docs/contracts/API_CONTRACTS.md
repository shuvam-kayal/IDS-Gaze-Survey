# API contract index

The cross-workstream API behavior is frozen in
[`architecture/INTEGRATION_FREEZE.md`](../architecture/INTEGRATION_FREEZE.md),
Section 6. This file points to the machine-readable response contracts.

- Request: [`event-envelope.v1.schema.json`](../../contracts/schemas/event-envelope.v1.schema.json)
- Success/duplicate response: [`event-ingestion-response.v1.schema.json`](../../contracts/schemas/event-ingestion-response.v1.schema.json)
- Validation/conflict response: [`event-error.v1.schema.json`](../../contracts/schemas/event-error.v1.schema.json)
- Success example: [`event-ingestion-response.json`](../../contracts/examples/event-ingestion-response.json)
- Validation example: [`event-error-invalid.json`](../../contracts/examples/event-error-invalid.json)
- Conflict example: [`event-error-conflict.json`](../../contracts/examples/event-error-conflict.json)

The accepted response has `status: "accepted"` with `duplicate: false`; an
exact retry has `status: "duplicate"` with `duplicate: true`. Both timestamps
must use UTC RFC 3339 (`Z` or `+00:00`). An exact retry returns the original
stored `ingested_at`, not a new retry-arrival timestamp.

The cross-owner browser boundaries are also machine-readable:

- Provider bridge: [`provider-sample.v1.schema.json`](../../contracts/schemas/provider-sample.v1.schema.json)
- Live AOI geometry: [`geometry-snapshot.v1.schema.json`](../../contracts/schemas/geometry-snapshot.v1.schema.json)
- Consolidated end-of-session survey: [`survey-plan.v1.schema.json`](../../contracts/schemas/survey-plan.v1.schema.json)

The survey plan is a separate session-scoped contract rather than an added
field on `SessionBootstrap`; this preserves the existing bootstrap v1 shape
while making the multi-study consolidation boundary explicit.

The `/v1/events` route now implements the frozen acceptance, exact-retry and
identity-conflict response behavior. Authentication, authorization and public
retrieval remain coordinated later work.
