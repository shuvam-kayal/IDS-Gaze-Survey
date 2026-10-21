# Blocker 3D.3 — Trusted Gaze Context Provider Interface Gap

Status: additive authorized provider path implemented. The frozen v1 endpoint
and `_gaze_context_provider` remain unchanged and fail-closed.

## Verified current interface

The frozen request is defined by:

- `contracts/schemas/gaze-observation-ingestion.v1.schema.json`
- `services/api/app.py::GazeObservationRequest`

It contains only `schema_version`, `request_id`, `session_id`, and a bounded
`provider_samples` array. `services/api/app.py::ingest_gaze_observation()`
passes `request.model_dump()` to `TrustedGazeContextProvider.resolve()`.

The participant credential is an HttpOnly cookie named
`ids_participant_session`, but the current gaze handler does not receive or
pass that cookie to the provider. The request also contains no study ID, trial
ID, or observation selector. A session can contain multiple studies, and a
study can contain multiple trial windows, so `session_id` alone cannot select
an unambiguous `AuthorizedGazeContext`.

The existing Blocker 3B resolver requires a server-selected `study_id` and
`trial_id`. The geometry resolver requires the same session, study, pinned
AOI-set version, and an observation-time boundary. None of those selectors are
present in the frozen v1 request. Provider samples cannot supply them because
provider payloads are measurement data, not authorization or lifecycle
context.

## Previous implementation blocker

The provider could not safely:

1. verify the participant credential without receiving the cookie or another
   server-authenticated credential handle;
2. choose one assigned study when a session has multiple assignments;
3. choose one trial and observation window; or
4. select the matching `server_validated` geometry snapshot.

Using browser-supplied values hidden in an ad hoc request key, inferring the
latest study/trial, or treating sample fields as context would bypass the
server-owned trust boundary. Changing the frozen v1 schema in place would also
violate the integration freeze.

## Approved additive resolution

The additive bridge has two parts:

### Public request selection

The new `1.1.0` companion contract contains untrusted selectors for exactly one `study_id` and
`trial_id` (and, if required by the selected design, an opaque observation
submission identity). The values remain untrusted selectors until the server
checks them against the participant's assignment and persisted Blocker 3B
lifecycle. The request must not accept `aoi_set_version`, window boundaries,
geometry, consent assertions, or provenance as authority.

The implemented contract is:

```json
{
  "schema_version": "1.1.0",
  "request_id": "request-1",
  "session_id": "session-from-bootstrap",
  "study_id": "study-a",
  "trial_id": "trial-a",
  "provider_samples": []
}
```

The server derives the effective session from the participant cookie;
`session_id` is only a consistency check and must not override credential
binding.

### Internal authenticated handoff

The API handler passes the cookie-derived, server-verified participant
session to `TrustedGazeContextProvider` through an internal handoff.
The public request body must never contain or expose the raw credential. The
handoff may be a new internal request object or a provider constructor
dependency, but it must make these inputs explicit:

- verified participant session;
- server-owned study assignment and pinned configuration;
- durable consent state;
- persisted Blocker 3B trial window;
- matching `server_validated` geometry resolved as of that window.

`TrustedGazeContextProvider.resolve()` returns the existing
`AuthorizedGazeContext` without
changing `ProviderSample`, `GazeRecord`, `FeatureRecord`, or persistence
schemas.

## Implementation and tests

The additive request and route require API/integrator, P1, P2, and P3 review
before production deployment. The implementation is in
`services/feature_engine/trusted_context.py` and
`services/api/app.py::ingest_authorized_gaze_observation`.

The approval change must add tests for credential/session binding, multiple
studies and trials, missing or stale trusted geometry, withdrawn/expired
sessions, lifecycle ambiguity, exact retries, and preservation of the current
503 fail-closed behavior until the provider is explicitly wired.

The frozen v1 schema and route were not changed. The additive schema is
`contracts/schemas/gaze-observation-ingestion.v1.1.schema.json` and the route
is `POST /v1/gaze/observations/authorized`. No migration was required.
