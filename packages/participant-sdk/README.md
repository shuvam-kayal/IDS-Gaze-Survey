# Participant SDK entry and bootstrap

`src/entry-widget.js` exports `mountParticipantEntry(root, options)`. It renders
an accessible invitation dialog and reports acceptance to the host application.
The host owns the next step: collect the applicable research consent before it
calls `fetchParticipantConfiguration`. The widget does not create a session or
emit research events when the participant declines.

`src/bootstrap.js` validates the server-provided `SessionBootstrap` against
`session-bootstrap.v1.schema.json`, checks that the returned Experience matches
the requested Experience, and rejects expired or unsupported versions. The
Experience ID is only a routing value. The browser's `Origin` header is
automatically supplied by the browser; the SDK never accepts an origin string
or treats it as authorization. The session/bootstrap endpoint must validate
that header against the server's configured Experience origin before issuing a
session, and return HTTP 403 for an unauthorized origin.

The frozen v1 contracts keep `StudyConfig` and `ConsolidatedSurveyPlan` as
separate records rather than adding fields to `SessionBootstrap`. The loader
fetches each StudyConfig using the version pinned in the bootstrap, validates
the survey timing and config versions, then fetches the matching session-scoped
SurveyPlan. It derives camera/modality options from the returned versioned
configuration; it does not invent Study IDs, versions, or survey timing.

The control-plane service implements the session/bootstrap and pinned-resource
endpoints under `/v1/sessions`. The SDK client keeps the endpoint configurable
so hosts can select their API origin. Do not treat a successful browser-side
origin check as security; authorization belongs on the server endpoint.

## Consent and withdrawal

`ConsentLifecycle` accepts policy text and versions supplied by the host, then
persists each research or camera decision through a separate
`persistConsent(record)` capability. The SDK keeps the decision in memory and
does not save consent data in browser storage or send it through the research
event queue. Research collection cannot be registered until the server confirms
the research choice. Camera capture requires a second accepted camera choice;
declining it still allows non-gaze participation under the current frozen
policy.

The host should call `startCamera` from a participant action after both
consents. The SDK does not call `getUserMedia` or pass a stream/camera
capability to the provider. It invokes the provider with:
`{ session_id, consent_granted: true, initial_geometry, on_sample, on_status }`.
The selected provider owns camera acquisition through its supported public API
and releases only resources it acquired. ProviderSamples pass through without
normalization.

Camera denial, missing APIs or devices, interruption, unplugging, permission
revocation, and provider startup failure produce a reason-coded
`non_gaze_only` state. The consent UI can display the status, offer retry where
appropriate, or let the participant continue without gaze. The `onContinue`
callback tells the host to launch the survey journey with the chosen modality
and missingness reason. Research and survey participation remain available,
and missing gaze is never filled with zero.

The P3 adapter implements this consent-gated bridge and must report
`initializing`, `ready`, `unavailable`, or `stopped`. Camera denial and provider
startup failure become explicit non-gaze status/missingness while research and
survey participation continue. `withdraw()` stops registered collectors and the
provider before invoking only the separately injected
`flushWithdrawalAudit()` capability. Generation guards discard late samples and
callbacks after stop or withdrawal, and repeated stop/withdrawal calls are safe.
The SDK never stops a foreign MediaStream. An approved, idempotent withdrawal
endpoint and secure consent persistence service still need to be supplied by
the control-plane integration.

## Trials, surveys, and interactions

`TrialLifecycle` consumes a host-provided timing rules object with a version,
optional `duration_ms`, `pause_on_hidden`, and optional `allow_pause`. It uses a
monotonic clock for `elapsed_ms`, emits only the frozen trial exposure start
and end EventEnvelopes with UTC timestamps, and makes terminal transitions
idempotent. The frozen StudyConfig v1 does not yet define this trial timing
object, so the host must supply the version-pinned rules.

`parseQuestionConfig` follows the frozen QuestionConfig v1. Survey presentation
order follows the ConsolidatedSurveyPlan; every response retains its Study and
question-set version. Choice and scale answers must match configured option
IDs. Because v1 has no numeric scale minimum/maximum fields, scale questions
need versioned `options` for validation. `createSurveyRuntime` freezes the
payload and IDs after the first valid submit so retries reuse the same
idempotency key and response IDs. The host supplies the persistence callback;
the live participant app uses the authenticated survey-response endpoint, while
offline demos may keep answers page-local.

`startInteractionCapture` accepts a versioned server-provided event allow-list and a
consented lifecycle controller. It records only event type, coordinates,
scroll position, visibility state, and configured AOI ID where available. It
never reads form values, passwords, labels, page text, or route URLs. Route
changes are reported explicitly with `recordNavigation()` and carry no path.

## Dynamic AOI geometry

`parseAoiConfig` validates versioned AOI selectors and identifiers.
`createGeometryTracker` emits GeometrySnapshot v2 in viewport-relative CSS
pixels (`*_px`), with the configured Study and AOI-set version. It tracks
window and nested scroll, resize, visual viewport zoom, DOM mutations, and
observed element resizes with debouncing. Hidden or missing elements are
omitted; overlapping AOIs retain their configured priority for downstream
resolution. One tracker is created per Study because GeometrySnapshot v2 is
Study-scoped. Snapshot delivery is an injected P3 callback; the server scaffold
does not yet expose a geometry ingestion endpoint.

## Event buffering and demo

`EventQueue` validates frozen EventEnvelope v1 records and bounds its in-memory
buffer by both event count and serialized byte size. Enqueueing a duplicate ID
with identical content is idempotent; reusing an ID with different content or
exceeding either bound is an explicit error. Dispatch uses the same `event_id`
in the `Idempotency-Key` header and removes an event only after a schema-valid
accepted or duplicate receipt. Transient network errors, HTTP 408/425/429, and
server errors retry with capped exponential backoff. Permanent rejection keeps
the event queued and returns the error for the host to surface.

The queue is in-memory, not persisted across reloads. `online` and `pagehide`
trigger a flush, and hosts should call `close()` at session termination. On
withdrawal, call `purge()` and detach lifecycle handlers; do not flush pending
research events as part of the withdrawal audit. `apps/participant-demo/`
shows the participant flow against a local, versioned sample fixture. Its
offline consent records and survey responses are demo-only in-memory examples;
live participant sessions use the server persistence routes.
