# Blocker 3A — Participant session and consent state

Status: secure server-issued session binding and authenticated participant
consent/withdrawal transport are implemented; geometry attestation and the
trusted gaze-context provider remain pending.

## Existing identity boundary

`services/control_plane/router.py::create_session_bootstrap` authorizes the
browser Origin against a published Experience and creates a server UUID. The
current `SessionBootstrap` contract contains that opaque `session_id`; the
participant binding is delivered separately as an HttpOnly cookie. The existing
authentication in `services/control_plane/auth.py` is for researcher/admin
users and is not reused for participant identity.

The cookie proves possession of one server-issued session credential, not a
real-world identity. A browser-provided `session_id` alone is not sufficient
proof of participant ownership. The binding is not yet used by consent routes
or the trusted gaze-context provider.

## Durable foundation

Migration `20261020_0004` adds:

- `participant_sessions`: server-issued session identity, Experience, open /
  closed / withdrawn status, issue and expiry timestamps, and update timestamps.
- `participant_consent_records`: one latest decision per session and scope,
  distinguishing `research_participation` from `camera_gaze`, with policy
  version and occurrence timestamp.

Migration `20261020_0005` adds a nullable unique SHA-256 credential verifier.
New bootstrap sessions receive a cryptographically random credential in the
`ids_participant_session` HttpOnly, SameSite=Strict cookie, scoped to `/v1`.
Only the verifier is persisted. Secure-cookie behavior follows
`PARTICIPANT_COOKIE_SECURE`; outside explicit development/test/local modes the
cookie is forced Secure even if the variable is set to `false`.

`ControlPlaneRepository` provides server-side persistence, credential
verification, consent recording, withdrawal and state lookup. Bootstrap creates
the session record and sets the binding cookie after the existing origin and
assignment checks. Invalid, expired, withdrawn and mismatched credentials fail
closed in the reusable verifier.

If a valid cookie for the same Experience is sent on a bootstrap retry, the
server reuses its existing session and assignment rather than creating another
session or rotating the credential. A cookie for another Experience does not
authorize access to that Experience; a new server-created session is issued.

Participant state-changing routes are now available at
`POST /v1/sessions/{session_id}/consent` and
`POST /v1/sessions/{session_id}/withdraw`. Both require the exact
`ids_participant_session` HttpOnly credential and an authorized browser
`Origin`; the path session ID is never accepted as authorization. Request
bodies are strict and accept only the existing two consent scopes or a UTC
withdrawal occurrence timestamp. Camera consent is rejected until durable
research-participation consent is accepted. Exact consent retries return the
stored decision with `duplicate: true`; conflicting reuse is rejected. A
successful withdrawal immediately changes the session to `withdrawn`, so a
later authorization attempt fails closed. SameSite=Strict, HttpOnly, `/v1`
cookie scoping, Secure deployment defaults, credentialed CORS, and exact Origin
checking remain in force; no separate participant CSRF token was introduced.
The SDK exposes small credentialed request helpers for hosts to bind to its
existing `persistConsent` and `flushWithdrawalAudit` callbacks. These helpers
do not authorize a session or imply that a browser callback is consent.

## Required next decision

P1 and the API/integrator must approve the cookie binding and its deployment
policy, including credentialed CORS, CSRF protection for future state-changing
routes, rotation and logout semantics. It binds possession of a session
credential to `participant_sessions.session_id`; it does not authenticate a
real-world participant.

The routes must be used by the participant host before consent can be consumed
by a trusted gaze context provider. Trial/exposure lifecycle and study-scoped
geometry remain separate 3B/3C prerequisites.

## Blocker 3B status

The P3 lifecycle foundation is implemented in
`services/gaze_engine/lifecycle.py` and documented in
`BLOCKER_3B_TRIAL_LIFECYCLE.md`. It derives a start-inclusive, end-exclusive
trial window from durably persisted `trial.exposure_started` and
`trial.exposure_ended` events only after a caller supplies an already-verified
participant session and server-owned study assignment. Missing, conflicting,
out-of-order, or incomplete lifecycle state remains fail-closed. This does
not complete geometry association or the production trusted gaze provider;
those remain Blockers 3C and 3D.
