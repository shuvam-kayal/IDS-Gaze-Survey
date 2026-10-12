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

The current API implementation is intentionally still a scaffold and returns
`persisted: false`. Implementing the frozen response behavior requires a
coordinated change to the shared API route and its tests.
