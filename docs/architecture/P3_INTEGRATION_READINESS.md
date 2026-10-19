# P3 Integration Readiness

Status: P3 pipeline complete; mock-backed M4 transport integration available;
production session authorization and participant-runtime binding remain
external work.

## Implemented architecture

```text
P1/provider callback
       │ ProviderSample v1
       ▼
POST /v1/gaze/observations
       │ request validation
       ▼
server-owned TrustedGazeContextProvider
       │ AuthorizedGazeContext
       ▼
process_authorized_gaze()
       ├── ProviderSampleAdapter.normalize_batch()
       ├── validate_observation_association()
       ├── process_trial_gaze()
       ├── persist_gaze_association()
       └── persist_feature_record()
       ▼
canonical GazeRecords + deterministic FeatureRecord
```

The browser request is only an untrusted lookup/submission. It does not
authorize itself. The API fails closed with `503 gaze_context_unavailable`
when no server-owned context provider is configured. Tests inject an explicit
provider through the private API module variable; this is not a production
authorization implementation.

The request represents one complete bounded observation for one study-scoped
trial. It is not an incremental streaming protocol. The existing association
identity is one deterministic association for `(session_id, study_id,
trial_id)` and its complete observation window.

## P3-owned interfaces

### Provider lifecycle

`packages/gaze-provider-webgazer/src/webgazer-adapter.js` implements the
frozen `ProviderAdapter` lifecycle:

```typescript
start({
  session_id,
  consent_granted: true,
  initial_geometry,
  on_sample,
  on_status,
}): Promise<void>

stop(): void
```

The adapter emits only ProviderSample v1 objects. It preserves
`confidence: null`, emits calibration/quality flags, rejects malformed or
out-of-bounds predictions, and stops only provider-owned camera resources.

The future P1 runtime must buffer a bounded complete trial observation and send
the structured ProviderSamples through the API route. It must call `stop()` on
denial, withdrawal, interruption, teardown or expiry.

### Trusted context

`services/feature_engine/context_provider.py` defines
`TrustedGazeContextProvider.resolve(request)`.

The provider must resolve and validate server-owned:

- `experience_id`;
- session state and expiry;
- consent/withdrawal eligibility;
- study eligibility and pinned `config_version`;
- pinned `aoi_set_version`;
- study-scoped `trial_id` and observation window;
- trial lifecycle start event;
- study-scoped GeometrySnapshot v2;
- interaction events and survey-derived context.

`services/feature_engine/authorized_gaze.py::AuthorizedGazeContext` is the P3
typed handoff. It validates internal consistency but does not authenticate or
authorize the caller.

### API request

The additive request contract is
`contracts/schemas/gaze-observation-ingestion.v1.schema.json`:

```json
{
  "schema_version": "1.0.0",
  "request_id": "gaze-request-0001",
  "session_id": "session-0001",
  "provider_samples": []
}
```

`provider_samples` is bounded to 250 objects and each object must satisfy the
existing ProviderSample v1 contract. `session_id` and `request_id` are
untrusted request keys until the context provider validates them.

The response contract is
`contracts/schemas/gaze-observation-ingestion-response.v1.schema.json`:

```json
{
  "schema_version": "1.0.0",
  "request_id": "gaze-request-0001",
  "status": "processed",
  "duplicate": false,
  "feature_record_id": "feat-...",
  "sample_count": 3
}
```

Exact retries return status `duplicate` when the existing association and
FeatureRecord identities are already present. Conflicting content is rejected
by the existing repository identity checks. Invalid input returns 422;
missing trusted context returns 503; identity conflicts return 409.

Existing `POST /v1/events` behavior is unchanged.

## Validation and processing rules

The API route in `services/api/app.py::ingest_gaze_observation`:

1. validates the additive request shape and batch limit;
2. obtains trusted context from the server-owned provider;
3. rejects context for a different session;
4. delegates to `process_authorized_gaze()`.

The P3 handler:

1. validates the trusted context and observation window;
2. normalizes ProviderSamples through `ProviderSampleAdapter`;
3. rejects duplicate, malformed, invalid or out-of-window samples;
4. validates the existing GazeObservationAssociation shape;
5. computes the FeatureRecord through `process_trial_gaze()`;
6. persists canonical gaze and association rows;
7. persists the FeatureRecord using its existing fingerprint and identity.

Canonical identities remain unchanged:

- gaze: `(session_id, sample_id)`;
- association: `(association_id, session_id)`;
- event: `(session_id, event_id)`;
- FeatureRecord: existing `feature_record_id` and fingerprint.

Samples are ordered by UTC `occurred_at`, then sample identity. Missing
coordinates remain missing; confidence remains nullable. No raw video or
provider-native object is persisted.

## Persistence and recovery guarantee

The current repository exposes separate transactions for association and
FeatureRecord persistence. The handler therefore computes before writing, then
writes the association followed by the FeatureRecord.

If FeatureRecord persistence fails after association persistence, the retry
reuses the same association identity and reconciles the missing FeatureRecord.
The retry is safe and does not duplicate canonical gaze rows. The handler does
not claim atomicity across both repository calls.

The existing PostgreSQL repository remains authoritative. No new table or
migration is required for this transport.

## Missing gaze and lifecycle behavior

Camera denial, missing consent, provider failure or interruption uses the
existing non-gaze path and reason codes. The handler accepts an explicitly
authorized unavailable-gaze context with no ProviderSamples and persists only
the resulting non-gaze FeatureRecord.

P1 owns consent, withdrawal, camera lifecycle, trial lifecycle and teardown.
P3 owns provider cleanup, normalization, quality and feature processing. P2
owns eligibility and pinned configuration. P4 consumes FeatureRecords and owns
analysis outputs.

## Replacement plan for mocks

| Mock/test double | Current purpose | Production replacement | Owner |
|---|---|---|---|
| API `_gaze_context_provider` injection | Supplies trusted context in API tests | Session/consent/eligibility/context service | API/integrator + P1/P2 |
| `FakeContextProvider` | Exercises route validation and retries | Authorized server-side resolver | API/integrator |
| `FakeRepository` in service tests | Tests handler ordering and recovery without DB setup | Existing `TelemetryRepository` | Database/P3 integration |
| Synthetic ProviderSamples | Deterministic pipeline coverage | Real WebGazer callback from P1 runtime | P1/P3 |
| Local smoke page | Manual provider diagnostics | Participant runtime | P1 |

Mocks are never valid authorization, participant data or production persistence
substitutes.

## Ownership checklist

### P1

- Implement participant runtime capture lifecycle.
- Gate provider start on explicit research consent.
- Provide trial start/end events and live GeometrySnapshot v2.
- Batch a complete trial observation and call the additive API route.
- Stop on withdrawal, interruption, teardown and expiry.

### P2

- Provide server-owned eligibility and immutable configuration lookup.
- Bind study and AOI-set versions to the session.

### P3

- Maintain adapter, normalization, quality, fixation/AOI, metrics and
  FeatureRecord behavior.
- Maintain the authorized internal handler and PostgreSQL persistence.
- Complete retention cleanup for gaze/features according to the frozen policy.

### P4

- Consume FeatureRecords without treating missing gaze as measured zero.
- Implement analysis-output persistence and deletion dependencies.

### API/integrator and database owner

- Replace the injected context provider with real authorization/context state.
- Configure production route authentication and rate limits.
- Run PostgreSQL migrations and integration tests.
- Preserve `/v1/events` compatibility.

## Commands

From the repository root:

```powershell
pytest -q tests/test_authorized_gaze.py tests/test_gaze_api.py tests/test_gaze_pipeline.py tests/test_contracts.py
pytest -q tests/test_telemetry_persistence.py
pytest -q
ruff check services/api/app.py services/feature_engine services/gaze_engine services/telemetry tests
python -m py_compile services/api/app.py services/feature_engine/authorized_gaze.py services/feature_engine/context_provider.py
git diff --check
alembic current
alembic heads
npm test --prefix .\packages\gaze-provider-webgazer
npm run build:smoke --prefix .\packages\gaze-provider-webgazer
npm run build:p3-demo --prefix .\packages\gaze-provider-webgazer
```

PostgreSQL persistence tests must be run against PostgreSQL 16 and must not be
replaced with SQLite or mocks.

## Status

Implemented and tested:

- P3 provider normalization and deterministic processing;
- trusted-context type boundary;
- additive request/response contracts;
- fail-closed additive API route;
- mock-backed route-to-P3 integration;
- retry and partial-persistence recovery behavior;
- existing non-gaze fallback.

Still externally pending:

- production API authorization/context provider;
- P1 participant runtime and real browser submission;
- P2 server-side eligibility/configuration service;
- P4 analysis-output integration;
- full PostgreSQL-backed route test in environments where PostgreSQL is
  unavailable.

This is not a claim that real browser-to-result M4 integration is complete.

## Local mock-backed workflow

`scripts/p3_local_demo.py` provides an isolated localhost development demo. It
loads the existing session-bootstrap, AOI-config, geometry-snapshot and
trial-exposure-start examples, binds them to one dedicated session, injects an
explicit test-only trusted context provider, and uses the real PostgreSQL
repository. It is not production authorization and it is not research data.

PowerShell commands:

```powershell
$env:P3_LOCAL_DEMO = "1"
$env:DATABASE_URL = "postgresql+psycopg://attention:attention@localhost:5432/attention?connect_timeout=5"
npm run build:p3-demo --prefix .\packages\gaze-provider-webgazer
python .\scripts\p3_local_demo.py
```

Open `http://127.0.0.1:8000/`. Choose deterministic synthetic mode for the
repeatable path, or the actual WebGazer mode for a consented provider check.
The page submits through `POST /v1/gaze/observations`, displays the response,
and retrieves only the dedicated demo session through its local report route.
The Reset button calls the existing session-scoped deletion method; it never
truncates tables or touches another session.

Available negative/recovery scenarios are invalid sample (422), context
mismatch (422), missing trusted context (503), injected FeatureRecord failure
followed by retry recovery, and camera-denied/non-gaze fallback. Select
`Exact retry` and submit twice to demonstrate the duplicate response. Camera
mode remains provider-only and does not persist video or frames.

The P3 launcher serves the explicit pinned FaceMesh allowlist under
`/mediapipe/face_mesh/`; `build:p3-demo` runs the existing asset-copy helper
before bundling. Camera startup errors are shown in the page and are not
treated as successful capture merely because provider initialization resolves.
