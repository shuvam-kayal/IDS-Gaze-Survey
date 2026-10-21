# Blocker 3D prerequisite — Geometry trust boundary

Status: geometry-trust decision implemented as a narrow server-validation
bridge; the production trusted gaze-context provider remains unset.

## Decision question

The repository now validates and persists GeometrySnapshot v2 records, but its
default provenance is `browser_submitted_untrusted`. The frozen architecture
requires P1 to capture live geometry, P2 to own AOI definitions and versions,
and P3 to perform timestamped mapping. Persistence alone cannot prove that a
browser-reported rectangle matches the participant's rendered page.

Therefore Blocker 3D must not authorize gaze processing from the current
geometry rows until the following server-side trust boundary is approved.

## Proposed smallest safe design

### 1. Producer and validator

P1's existing `createGeometryTracker()` produces GeometrySnapshot v2 values
from the participant DOM and calls its `onSnapshot` callback. This is the
geometry producer; it is not an authorization source and is not currently
connected to a production gaze-ingestion route.

The API/integrator-owned participant bridge should submit the snapshot to a
server-side geometry service. That service should call P3's existing
`validate_geometry_snapshot()` and `TelemetryRepository.persist_geometry_snapshot()`
only after resolving the participant session and assignment server-side.
P2's `ControlPlaneRepository.get_assignment()` remains the source of the
pinned study configuration and AOI-set version.

No browser-supplied `session_id`, `study_id`, `aoi_set_version`, or geometry
field is trusted merely because it passes JSON validation.

### 2. Required consistency checks

The server-side bridge must verify all of the following before accepting a
snapshot for trusted gaze processing:

- the participant credential resolves to the same open, unexpired session;
- the session is not withdrawn or closed;
- the requested study is present exactly once in the server-owned assignment;
- the snapshot's `study_id` and `aoi_set_version` equal the assignment's
  pinned values;
- the snapshot's `session_id` equals the credential-bound session;
- every rectangle has a configured AOI ID from the pinned AOI configuration;
- rectangle priority and geometry follow the v2 contract and freeze rules;
- `captured_at` is valid UTC and the snapshot is selected only when
  `captured_at <= observation_time`;
- the selected snapshot is scoped to the same session, study, and AOI-set
  version as the Blocker 3B trial window.

P3's existing resolver already provides exact-scope and as-of-time selection:
`TelemetryRepository.resolve_geometry_snapshot()`.
`services/gaze_engine/geometry.py` validates the v2 shape and rectangle
semantics. The missing part is the approved server-side attestation that the
validated snapshot is eligible for authorization.

### 3. Proposed provenance marker

The server-only provenance value is:

```text
server_validated
```

It may be assigned only by the server-side geometry bridge after all checks
above succeed. Browser requests
must not be allowed to provide or select this value. Existing rows remain
`browser_submitted_untrusted`; none may be upgraded automatically.

The bridge is implemented in
`services/gaze_engine/geometry_bridge.py` and is called by the authenticated
participant geometry route. It remains an internal persistence marker
metadata and must not change GeometrySnapshot v2 or the public gaze request
contract.

### 4. Consent, expiry, and withdrawal

The durable control-plane model can distinguish:

- `research_participation` consent; and
- `camera_gaze` consent.

`ControlPlaneRepository.participant_consent_state()` reads those scopes,
`record_participant_consent()` stores them, and
`withdraw_participant_session()` changes the participant session to
`withdrawn`. `verify_participant_session()` already rejects missing,
withdrawn, closed, and expired sessions.

Participant-facing consent and withdrawal routes now persist these scopes at
`POST /v1/sessions/{session_id}/consent` and
`POST /v1/sessions/{session_id}/withdraw`. They require the server-issued
HttpOnly session credential, an authorized Origin, and strict request bodies;
the path session ID is not authorization. Camera consent requires accepted
research consent, and withdrawal immediately makes the credential fail closed.
The SDK exposes credentialed helpers for hosts to call these routes. Consent
must still not be inferred from browser callbacks, cookie possession, or
provider startup, and the production provider does not consume these records
until the trusted geometry and context bridge exists.

This is an unresolved prerequisite for 3D: the API/integrator and P1 must
approve the state-changing consent/withdrawal bridge and its CSRF/lifecycle
semantics before the provider authorizes gaze processing.

## Security guarantee and limitation

The proposed boundary would guarantee that P3 processes geometry only when its
identity, study assignment, AOI version, timestamp, and session scope agree
with server-owned state. It would prevent cross-session and cross-study
geometry selection and reject stale or malformed snapshots.

It would not prove that the browser actually rendered those rectangles, that
the participant saw the intended page, that the DOM was not modified, or that
the geometry is scientifically accurate. Those remain browser/runtime and
measurement limitations and must be represented as quality limitations, not
silently promoted to authorization.

## Future P3 provider interface

The provider should continue to consume the existing internal interface:

```python
AuthorizedGazeContext = {
    "experience_id": ...,
    "session_id": ...,
    "study_id": ...,
    "trial_id": ...,
    "aoi_set_version": ...,
    "observation_context": TrialObservationContext(...),
    "geometry_snapshots": [...],
    "events": [...],
    "start_event": ...,
    ...,
}
```

`TrustedGazeContextProvider.resolve(request)` now derives this object from the
API-verified participant session, server assignment, consent state, Blocker 3B
lifecycle resolver, and `server_validated` geometry snapshots. It is exposed
only through the additive `1.1.0` authorized request path; the frozen v1 gaze
observation request and route remain unchanged and fail-closed.

## Proposed team decision

The bridge now assigns `server_validated` only after P1 session/consent state,
P2 assignment/AOI configuration, persisted Blocker 3B lifecycle, and P3 v2
validation agree. It preserves existing `browser_submitted_untrusted` rows and
keeps `/v1/gaze/observations` fail-closed until the full trusted context
provider is implemented and approved.

## Unresolved blockers

1. P1/API approval of the server-side geometry attestation path and participant
   consent routes.
2. A production connection from the participant geometry tracker to the
   approved server bridge.
3. PostgreSQL-backed integration tests proving the complete authorized path.

## Files inspected

- `docs/architecture/INTEGRATION_FREEZE.md`
- `docs/architecture/BLOCKER_3A_STATE.md`
- `docs/architecture/BLOCKER_3B_TRIAL_LIFECYCLE.md`
- `docs/architecture/BLOCKER_3C_GEOMETRY.md`
- `contracts/schemas/geometry-snapshot.v2.schema.json`
- `contracts/schemas/aoi-config.v1.schema.json`
- `services/gaze_engine/geometry.py`
- `services/gaze_engine/lifecycle.py`
- `services/telemetry/persistence.py`
- `services/control_plane/store.py`
- `services/control_plane/participant_auth.py`
- `services/api/app.py`
- `packages/participant-sdk/src/geometry.js`
- `packages/participant-sdk/src/consent-lifecycle.js`
