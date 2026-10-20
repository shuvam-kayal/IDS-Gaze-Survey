# Blocker 3D prerequisite — Geometry trust boundary

Status: proposed decision; no geometry is marked trusted and the production
trusted gaze-context provider remains unset.

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

The proposed internal provenance value is:

```text
server_validated
```

This is a proposal, not an implemented value. It may be assigned only by the
server-side geometry bridge after all checks above succeed. Browser requests
must not be allowed to provide or select this value. Existing rows remain
`browser_submitted_untrusted`; none may be upgraded automatically.

Adding or enforcing this marker in production code requires approval from the
API/integrator, P1, P2, and P3 owners. It should remain internal persistence
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

However, the repository has no approved participant-facing consent or
withdrawal HTTP endpoints. The participant demo still uses explicitly
documented in-memory callbacks. Consequently, the production provider cannot
yet claim that camera consent was durably granted or that withdrawal has been
delivered through the real participant path. Consent must not be inferred from
browser callbacks, cookie possession, or provider startup.

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

The future `TrustedGazeContextProvider.resolve(request)` should derive this
object from the verified participant credential, server assignment, consent
state, Blocker 3B lifecycle resolver, and a `server_validated` geometry
snapshot. The browser request remains only an untrusted lookup/submission key;
the frozen gaze-observation request and response contracts need not change.

## Proposed team decision

Approve the server-only `server_validated` provenance marker and a narrow
API/integrator geometry bridge that may assign it only after P1 session/consent
state, P2 assignment/AOI configuration, and P3 v2 validation agree. Require
the bridge to preserve the current `browser_submitted_untrusted` records and
keep `/v1/gaze/observations` fail-closed until that bridge and the consent /
withdrawal lifecycle are implemented and tested.

## Unresolved blockers

1. P1/API approval of the server-side geometry attestation path.
2. P1/API approval and implementation of durable participant consent and
   withdrawal transport.
3. A production connection from the participant geometry tracker to the
   approved server bridge.
4. PostgreSQL-backed integration tests proving the complete authorized path.

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
