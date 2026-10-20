# M4 Browser-to-Result Transport Decision

Status: selected design; fail-closed route scaffolding implemented; production
authorization/runtime binding remains pending

This decision records the smallest compatible transport for connecting the P1
participant runtime to the existing P3 gaze pipeline. It does not change the
frozen contracts and does not claim that browser-to-result integration is
complete.

## Problem and current boundary

The WebGazer adapter in
`packages/gaze-provider-webgazer/src/webgazer-adapter.js` emits frozen
`ProviderSample` objects through its `on_sample` callback. The smoke page in
`packages/gaze-provider-webgazer/src/browser-smoke-entry.js` only displays
those samples locally.

P3 already provides the processing boundary:

1. `services/gaze_engine/adapter.py::ProviderSampleAdapter.normalize_batch`
   converts ProviderSamples into canonical GazeRecords.
2. `services/feature_engine/gaze_pipeline.py::process_trial_gaze` validates
   study, trial, geometry and observation-window context and builds a
   FeatureRecord.
3. `services/telemetry/persistence.py::persist_gaze_association` persists
   canonical gaze and its study/trial association.
4. `services/telemetry/persistence.py::persist_feature_record` persists the
   deterministic derived record.

The missing link is an authorized browser-to-server request that supplies
ProviderSamples together with P1/P2-owned session and trial context.

## Selected transport

Use a small additive HTTP request to the existing FastAPI service. The request
must be a separately versioned provider-ingestion contract; it must not
overload the existing `POST /v1/events` EventEnvelope semantics.

The final public route name and request schema identifier require API/integrator
approval. The implementation target is an additive route equivalent to:

```text
POST /v1/gaze/observations
```

The route is preferred because the repository already uses FastAPI request
models and PostgreSQL repository transactions, and because an observation
submission can carry the complete study/trial/window context required by P3.
It also permits bounded batches without introducing a WebSocket, queue,
browser database or direct browser-to-database connection.

The additive route and versioned request/response contracts are now implemented
with a fail-closed server-side context-provider boundary. The production
context provider and participant runtime remain external work.

## Candidate request semantics

The additive request should contain:

- `schema_version` for the new transport contract;
- `session_id` from the P1/P2 session bootstrap;
- one study-scoped `trial_id`;
- the pinned `study_id` and `aoi_set_version`;
- an explicit `association_id` created by the authorized P1/P3 bridge;
- `window_start` and `window_end`, using the existing start-inclusive,
  end-exclusive association semantics;
- the relevant study-scoped GeometrySnapshot v2;
- one bounded array of ProviderSample v1 objects;
- the associated `trial.exposure_started` context when required by the P3
  metric pipeline;
- a transport request identity for retry handling.

The request must reuse these existing contracts without changing their
meanings:

- `contracts/schemas/provider-sample.v1.schema.json`;
- `contracts/schemas/gaze-observation-association.v1.schema.json`;
- `contracts/schemas/gaze-record.v1.schema.json`;
- `contracts/schemas/session-bootstrap.v1.schema.json`;
- `contracts/schemas/geometry-snapshot.v2.schema.json`;
- `contracts/schemas/trial-exposure-start.v1.schema.json`.

The browser must not be allowed to select an arbitrary latest study, geometry
snapshot, configuration version or AOI set. The server-side authorized session
context must bind those values before P3 processing.

## Response and error semantics

The new transport should define deterministic responses for:

- accepted observation batch;
- exact retry, returning the original server ingestion metadata;
- conflicting request identity, rejected as a conflict;
- invalid ProviderSample, timestamp, coordinate or context, rejected as
  validation failure;
- closed, withdrawn, expired or unauthorized session, rejected without
  persisting samples.

Existing `POST /v1/events` behavior remains unchanged, including its 202/200
acceptance and duplicate responses and 409/422 error semantics.

## Processing and transaction boundary

After authorization and request validation, the handler should:

1. normalize ProviderSamples through `ProviderSampleAdapter`;
2. create the existing association-shaped object;
3. persist the association and canonical GazeRecords through
   `TelemetryRepository.persist_gaze_association`;
4. run the existing study/trial pipeline with the validated context;
5. persist the resulting FeatureRecord through
   `TelemetryRepository.persist_feature_record`.

The request must not persist raw video, camera frames or provider-native
objects. Partial failures must roll back the request's durable writes or use
the existing retry-safe repository behavior; they must not produce a FeatureRecord
that claims data was persisted when the associated gaze write failed.

## Consent, interruption and withdrawal

P1 remains responsible for research consent, participant UI, camera lifecycle,
session lifecycle and withdrawal. P1 calls the provider only after explicit
consent and stops it on denial, withdrawal, teardown or expiry.

P3 continues to require `consent_granted: true` at provider startup, preserves
nullable confidence and quality flags, and maps provider failure to the
existing non-gaze missingness reasons.

Camera denial, missing consent, provider failure and interrupted capture must
produce the existing `non_gaze_only` behavior. They must not become numeric
zero gaze measurements and must not prevent non-gaze processing.

## Idempotency and ordering

The transport must preserve the existing identities:

- transport/event request identity: `(session_id, event_id)` if the approved
  transport reuses EventEnvelope identity, otherwise an explicitly versioned
  equivalent;
- canonical gaze identity: `(session_id, sample_id)`;
- association identity: `(association_id, session_id)`;
- FeatureRecord identity and fingerprint: existing repository rules.

Exact retries are no-ops. Conflicting identity reuse is rejected. Provider
samples retain their UTC `occurred_at`; P3 retrieves and processes them in
deterministic timestamp/identity order. Late events follow existing stale or
reprocessing behavior and must not silently overwrite a completed result.

## Alternatives rejected

### Reusing `POST /v1/events`

Rejected for the initial design because the frozen EventEnvelope contract does
not define ProviderSample or gaze-association payload semantics. Overloading
the route would make interaction and gaze identity, validation and retry
behavior ambiguous.

### WebSocket or streaming transport

Rejected because no approved WebSocket lifecycle, authorization, backpressure
or retry infrastructure exists in the repository. A bounded HTTP batch is
adequate for the first integration slice.

### Queue, polling service or browser database

Rejected because none exists in the current architecture and each would add
new durability, ordering and deletion responsibilities.

### Direct browser-to-database access

Rejected for security, authorization and ownership reasons.

## Ownership and required approval

- P1 supplies consented lifecycle invocation, session identity, trial events,
  live geometry and withdrawal behavior.
- P2 supplies eligibility and immutable pinned study/configuration versions.
- P3 owns ProviderSample normalization, canonical gaze, quality, processing,
  persistence and deterministic FeatureRecords.
- API/integrator owns the additive route, request model, authorization hook and
  response wiring.
- The database owner/integrator reviews any migration or transaction-path
  change; this design does not require a migration by itself.
- P4 reviews downstream FeatureRecord consumption and analysis deletion
  dependencies.

## Current blocker

The repository still does not contain:

1. a P1 participant runtime that sends ProviderSamples to the API;
2. server-side session authorization or a consent/withdrawal state store;
3. a production API authorization/context provider;
4. a P1 participant runtime that invokes the new route.

The browser must not be permitted to self-assert consent or eligibility as a
substitute for those controls. The implemented route returns
`gaze_context_unavailable` until the server-owned provider is configured; its
test-only injection is not production authorization.

## Smallest follow-up implementation slice

After the blocker is resolved, implement one authorized bounded observation
submission and test it against PostgreSQL:

1. replace the test-only context provider boundary with a real server-side
   authorization/context provider;
2. bind the P1 participant runtime to the additive route;
3. call the existing P3 normalization, association persistence and FeatureRecord
   pipeline;
4. test exact retries, conflicts, wrong context, withdrawal, camera denial,
   multi-study isolation and deletion;
5. exercise the route from the P1 runtime with a real WebGazer callback.

Until those steps are complete, M4 remains partial and the smoke page remains
diagnostic only.
