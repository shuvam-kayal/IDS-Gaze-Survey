# Blocker 3B — Trusted trial lifecycle and observation windows

Status: lifecycle/window foundation implemented; geometry and production gaze
authorization remain pending Blockers 3C and 3D.

## Scope

This slice derives a bounded, study-scoped observation window from the existing
durably persisted EventEnvelope records. It does not create a second trial
store, establish geometry, authenticate a browser, or wire the production gaze
context provider.

The reusable boundary is
`services.gaze_engine.lifecycle.resolve_authorized_trial_lifecycle`. Its
caller must first obtain `participant_session` from the existing server-issued
credential verifier and `study_assignment` from the server-owned control-plane
assignment store. Those dictionaries are trusted inputs to this P3 boundary;
the function does not authenticate them.

## State machine and event rules

The canonical lifecycle events are:

- `trial.exposure_started`, with exactly one `study_ids` value and
  `payload.trial_id`;
- `trial.exposure_ended`, with the same scope and trial identifier.

The derived states are:

```text
missing start or missing end -> incomplete (not gaze-authorized)
one valid start + one valid end -> closed observation window
end at/before start -> invalid (not gaze-authorized)
more than one non-identical start or end -> ambiguous (not gaze-authorized)
```

An exact `(session_id, event_id)` retry is already collapsed by the durable
telemetry repository. The pure resolver also accepts repeated identical event
objects as one event. A different payload, type, timestamp, study or session
with the same event identity is rejected by the existing ingestion conflict
rules; a second distinct lifecycle event of the same type makes the window
ambiguous rather than choosing one.

Events retain their client `occurred_at` and server `ingested_at`. Window
boundaries use `occurred_at`, not ingestion order or server arrival time. Valid
late and out-of-order events are accepted by telemetry persistence. Re-resolving
the persisted set after a late event is deterministic; a second competing
boundary does not silently extend or rewrite a previously usable window and is
reported as ambiguous. There is no streaming watermark in this release.

The interval is start-inclusive and end-exclusive. Samples at the start are
eligible; samples at the end are not.

## Trusted scope

The resolver checks, before reading lifecycle events:

1. the verified session is open and not expired;
2. the assignment belongs to that session and Experience;
3. exactly one requested study is assigned;
4. the requested AOI-set version equals the pinned study configuration;
5. each lifecycle event is for the verified session, Experience, exactly that
   study, and the requested trial.

The browser cannot override session ownership, assignment, Experience, study,
trial, or AOI-set version through this boundary. Missing or ambiguous state
returns a reason code or a validation error and must not authorize gaze
processing.

## Internal consumer interface

Blocker 3D may call:

```python
context, reason = resolve_authorized_trial_lifecycle(
    telemetry_repository,
    participant_session=verified_session,
    study_assignment=server_assignment,
    study_id=study_id,
    trial_id=trial_id,
    aoi_set_version=pinned_aoi_set_version,
)
```

`context` is a validated `TrialObservationContext` when `reason is None`.
The future trusted gaze context provider must additionally supply consent,
study-scoped GeometrySnapshot v2, requested AOI, interaction events and any
other fields required by `AuthorizedGazeContext`. This slice deliberately does
not construct that provider or make `/v1/gaze/observations` accept browser
context.

## Deliberate limitations and ownership

- P1 still owns participant-facing trial lifecycle emission and must emit both
  canonical events.
- P2/API integration still owns the authenticated bridge from participant
  credentials, assignment and consent state to P3.
- Blocker 3C still owns durable study-scoped geometry retrieval and snapshot
  association.
- Blocker 3D still owns the production `TrustedGazeContextProvider`.
- No consent or withdrawal endpoint, raw video storage, database migration, or
  public convenience endpoint was added.

The implementation is derived from the current frozen v1 events and existing
PostgreSQL persistence. No new contract version is required for this slice.
