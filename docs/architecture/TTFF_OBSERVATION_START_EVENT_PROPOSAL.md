# Proposal: TTFF observation-start event

Status: proposal only; not a frozen contract

This document resolves the contract gap identified before implementing
checklist item V. It proposes the smallest lifecycle addition needed to measure
time to first fixation (TTFF). It does not modify a schema, implementation,
database migration, API, or the project-wide integration freeze.

## Existing definitions

The proposal is constrained by these existing decisions:

- `docs/architecture/INTEGRATION_FREEZE.md §1` establishes `trial_id` as a P1
  runtime identifier carried in event payloads where applicable.
- The same section states that a session may contain multiple studies and that
  an `EventEnvelope.study_ids` array preserves the immutable study context.
- `docs/architecture/INTEGRATION_FREEZE.md §3` makes `occurred_at` the
  client-observed UTC occurrence time and `ingested_at` the server arrival time.
  Events may arrive late or out of order; retrieval is ordered by occurrence
  time, ingestion time, and event ID.
- `docs/architecture/INTEGRATION_FREEZE.md §10` defines TTFF from the pinned
  trial/exposure start event to the first qualifying fixation in the requested
  AOI.
- `contracts/schemas/event-envelope.v1.schema.json` requires a session-scoped
  `event_id`, `experience_id`, `study_ids`, `session_id`, `event_type`,
  `occurred_at`, and object `payload`, but does not enumerate lifecycle event
  types or payload shapes.
- `contracts/schemas/interaction-event.v1.schema.json` enumerates only click,
  hover, scroll, navigation, and visibility events. It is not a trial
  lifecycle contract.
- `contracts/schemas/geometry-snapshot.v1.schema.json` supplies the live
  `aoi_set_version`, session, timestamp, viewport, and AOI rectangles used by
  P3's timestamped mapping.
- `contracts/schemas/session-bootstrap.v1.schema.json` supplies the pinned
  study/config/AOI-set versions for each eligible study, but defines no trial
  or exposure identifier.
- No existing contract defines `exposure_id`, and no existing fixture defines
  a trial/exposure-start event.

## Proposed semantics

### Meaning and timing

Observation start means the instant at which P1 presents the trial exposure to
the participant and the exposure becomes eligible for gaze observation under
the already-granted consent and pinned session configuration. It is emitted
once per trial observation attempt, before or at the first participant-visible
exposure state. It is not the time the event reaches the server and is not the
time the first gaze sample arrives.

This definition deliberately does not claim that a gaze sample exists at the
start. If camera capture is unavailable or denied, the event may still exist
for the non-gaze workflow, but TTFF remains unavailable.

### Candidate event identity and type

Candidate event type: `trial.exposure_started`.

This name is a proposal, not a frozen value. It combines the existing freeze's
phrasing (“trial/exposure start event”) while retaining the established
`trial_id` domain concept. P1 must confirm whether the runtime calls this
boundary a trial start, exposure start, or another lifecycle term before a
schema/example is added.

The event uses the existing durable identity `(session_id, event_id)` from the
freeze. `event_id` is stable across retries of the same logical start event.

### Identifiers

Required proposed payload identifier:

- `trial_id`: the existing P1 runtime trial identifier defined in the freeze.

No `exposure_id` is proposed as required. It has no existing domain definition,
generator, relationship, or contract. If the P1 runtime later distinguishes
multiple exposures within one trial, that must be introduced as a separately
reviewed identifier with an explicit relationship to `trial_id`.

The envelope's `study_ids` remains the authoritative study context. A session
can contain multiple studies, so P3 evaluates the same start timestamp
against each applicable study-scoped FeatureRecord rather than inventing a
single study assignment.

### Timestamp

TTFF uses the start event's `occurred_at`, normalized according to the frozen
UTC RFC 3339 rule in `INTEGRATION_FREEZE.md §3`. It does not use `ingested_at`,
provider capture time, or the timestamp of the first sample as a substitute.

The event must be emitted with the occurrence timestamp corresponding to the
participant-visible exposure transition. Existing ingestion rules remain in
force for naive, non-UTC, malformed, duplicate, late, or conflicting event
payloads.

### Study, trial, exposure, and AOI-set association

The proposed association is:

1. `session_id` identifies the browser session.
2. `study_ids` identifies the applicable immutable study context.
3. `payload.trial_id` identifies the P1 trial lifecycle instance.
4. The session bootstrap supplies the pinned study `config_version` and
   `aoi_set_version`.
5. Timestamped geometry snapshots supply the live AOI rectangles and their
   `aoi_set_version` at mapping time.

The start event does not carry an `aoi_set_version` or a target AOI in this
minimal proposal. The metric request supplies the requested `aoi_id`; P3 must
validate it against the applicable AOI configuration/version and use the
timestamped geometry snapshots already defined for mapping. A future contract
may add explicit exposure-to-AOI targeting if the product requires it, but it
is not justified by the current domain model.

## Lifecycle and error handling

- Exact retry: handled by the frozen `(session_id, event_id)` identity and
  canonical payload comparison. It is acknowledged as a duplicate and does
  not create another start.
- Conflicting reuse: the frozen identity rule rejects reuse of the same event
  identity with a different payload, event type, context, or timestamp.
- Late arrival: accepted when valid under the frozen ingestion rules. The
  relevant derived processing scope becomes stale and is recomputed; the event
  does not mutate its original occurrence time.
- Multiple non-identical starts for the same `(session_id, trial_id)`: the
  proposed safe default is to mark that trial observation ambiguous and return
  TTFF unavailable rather than silently selecting one timestamp. P1 and P3
  must approve whether the runtime instead guarantees one logical start or
  supplies a distinct exposure identifier.
- Missing start event: TTFF is unavailable, represented by a null metric value
  and an explicit reason; it is not zero.
- No qualifying fixation in the requested AOI: TTFF is unavailable, represented
  by a null metric value and an explicit reason; it is not zero.
- Camera denial, provider failure, interrupted capture, or no gaze samples:
  the existing `non_gaze_only` path remains valid and no gaze metric is
  fabricated.

## Metric missingness representation

The frozen FeatureRecord schema permits arbitrary JSON values inside
`features`, while `quality.missingness` is the existing reason-code array. The
proposal is to represent a metric as an object when its value needs provenance
or missingness, for example:

```json
{
  "gaze.ttff_ms": {
    "value": null,
    "unit": "ms",
    "missingness": "gaze.observation_start_missing",
    "time_window": "trial",
    "aoi_set_version": "aoi-v1",
    "feature_algorithm_version": "gaze-baseline-1"
  }
}
```

The example is illustrative and is not a frozen contract. A measured zero is
represented as numeric `0`; an unavailable or undefined metric is represented
as `null` with a reason. Candidate reason codes requiring owner agreement are
`gaze.observation_start_missing`, `gaze.no_qualifying_fixation`, and
`gaze.metric_undefined`. Existing standard camera and sample reasons remain
those listed in `INTEGRATION_FREEZE.md §8`.

The same representation should be used consistently for dwell, revisits,
transitions, entropy, and scan paths when their input is absent or undefined.
The exact feature-key/object convention requires P3 implementation agreement
and P4 consumer review because no current FeatureRecord example defines
metric-level provenance objects.

## Illustrative proposal event

The following is a proposal example only; it is not a contract fixture:

```json
{
  "schema_version": "1.0.0",
  "event_id": "evt-trial-exposure-start-0001",
  "experience_id": "exp-demo-store",
  "study_ids": ["study-product-evaluation"],
  "session_id": "session-synthetic-0001",
  "participant_id": null,
  "event_type": "trial.exposure_started",
  "occurred_at": "2026-01-01T10:00:00Z",
  "payload": {
    "trial_id": "trial-0001"
  }
}
```

## Approval and follow-up

Required approvals:

- P1: semantic timing, event name, emission point, trial lifecycle, and
  duplicate/multiple-start behavior.
- P3: TTFF input interface, late-event invalidation, metric-level missingness,
  and feature algorithm metadata.
- P2: confirmation that the study/config/AOI-set association is compatible
  with immutable published configuration and multi-study sessions.
- P4: consumer acceptance of nullable metric objects, reason codes, units,
  windows, and limitations.

After approval, the smallest coordinated change is:

1. Add or update the versioned lifecycle event contract and TypeScript type
   according to the approved event name and payload.
2. Add one proposal-derived event fixture and contract tests, including exact
   retry, late arrival, missing start, and duplicate/conflicting behavior.
3. Update the integration freeze or its linked lifecycle contract through the
   documented contract-change process.
4. Only then implement Slice V metric calculations and tests.

No schema, implementation, migration, API, or test changes are made by this
proposal.
