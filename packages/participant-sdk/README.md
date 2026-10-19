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

The current API scaffold does not yet implement a session/bootstrap endpoint.
The SDK client and tests use a configurable endpoint so it can integrate when
the control-plane service is available. Do not treat a successful browser-side
origin check as security; authorization belongs on that server endpoint.

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
consents. It requests video only, passes the stream and geometry through the
P3 `ProviderAdapter` interface, and forwards ProviderSamples without
normalization. `withdraw()` stops registered collectors, camera tracks and the
provider before invoking only the separately injected
`flushWithdrawalAudit()` capability. It never flushes ordinary research events.
An approved, idempotent withdrawal endpoint and secure consent persistence
service still need to be supplied by the control-plane integration; until then,
the SDK reports an unconfigured audit sink and will not accept research
consent without that sink.
