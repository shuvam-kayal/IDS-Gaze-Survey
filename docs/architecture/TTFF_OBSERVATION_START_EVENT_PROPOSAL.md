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

The existing contracts also do not define whether `trial_id` is unique within
one session, one study, or a wider scope. The freeze identifies and generates
it in the P1 runtime, but does not state whether a trial belongs to exactly one
study or can be shared by several studies. This is a real cross-owner gap, not
something P3 can infer from the identifier shape.

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

The envelope's `study_ids` remains the authoritative study context. However,
that array alone is insufficient to select one study-scoped FeatureRecord when
the same trial is shared by multiple studies, because each eligible study may
have a different `aoi_set_version` and the FeatureRecord schema has exactly one
`study_id`.

Recommended minimal resolution: define the proposed start event as
study-scoped and require exactly one entry in its existing `study_ids` array.
That selects the FeatureRecord's `study_id` without adding a new field. Under
this recommendation, P1 must either create a distinct `trial_id` per study or
explicitly define a shared trial as producing separate study-scoped start
events. If the product requires one shared trial event for several studies,
the event contract must instead define an explicit per-study association; P3
must not guess which AOI set applies.

The current model does not establish this recommendation. P1 owns trial
lifecycle semantics; P2 owns study configuration and AOI-set versions; P3
owns the derived FeatureRecord selection. P1 and P2 must approve the trial
scope, with P3 and P4 reviewing the resulting metric interface.

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
minimal proposal. The selected study's pinned bootstrap/configuration supplies
the expected `aoi_set_version`; the metric request supplies the requested
`aoi_id`; P3 must validate both against the study-scoped AOI configuration.

There is a second concrete gap in the current geometry contract. The frozen
`GeometrySnapshot` contains `session_id` and one `aoi_set_version`, but no
`study_id`. Slice U's `_snapshot_for` in
`services/gaze_engine/fixation.py` therefore selects the latest prior snapshot
by session and time only. In a multi-study session it can select a snapshot
for the wrong study/AOI set. Matching only `aoi_set_version` at a higher layer
is not a complete identity guarantee because the contracts do not state that
AOI-set version strings are globally unique across studies.

Recommended minimal contract resolution: add required `study_id` to a new
version of `GeometrySnapshot` (a required field is not a backward-compatible
patch to the current `additionalProperties: false` v1 schema). The mapping
interface should then require the requested `study_id` and expected
`aoi_set_version`, filtering by session, study, version, and timestamp. Until
that change is approved, P3 may map only a single-study session or an
explicitly pre-filtered snapshot collection; it must not claim correct
multi-study mapping.

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
The existing non-gaze implementation uses scalar feature values and puts the
session-level gaze reason in `quality.missingness`. The following per-metric
object is therefore a proposed convention requiring P3 implementation
agreement and P4 consumer approval; it is not currently frozen:

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

The intended semantic distinction is:

- Measured zero: numeric `0`, with no missingness reason for that metric.
- Valid nonzero result: the measured numeric value.
- Unavailable result: `value: null` plus a reason such as
  `gaze.observation_start_missing` or `gaze.no_qualifying_fixation`.
- Undefined metric: `value: null` plus `gaze.metric_undefined`, for example
  entropy with fewer than two valid AOI observations as defined by the freeze.
- Gaze unavailable: `value: null`, with the existing session-level reason such
  as `gaze.permission_denied`, `gaze.no_samples`, or `gaze.provider_failure`,
  and `modality: non_gaze_only` where the FeatureRecord contains only non-gaze
  features.

The candidate metric reason codes and the object convention require owner
agreement. They must not be treated as additions to the frozen standard list
in `INTEGRATION_FREEZE.md §8` until the contract-change process approves them.
If the team chooses scalar metric fields instead, the same null-versus-zero
semantics and reason provenance must still be preserved through the approved
FeatureRecord convention.

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

- P1: semantic timing, event name, emission point, trial lifecycle, `trial_id`
  uniqueness/scope, whether a trial belongs to one study or can be shared,
  and duplicate/multiple-start behavior.
- P3: TTFF input interface, late-event invalidation, metric-level missingness,
  feature algorithm metadata, and the study/version filters used by mapping.
- P2: confirmation that the study/config/AOI-set association and proposed
  `GeometrySnapshot` study scope are compatible with immutable published
  configuration and multi-study sessions.
- P4: consumer acceptance of nullable metric objects, reason codes, units,
  windows, and limitations.

After approval, the smallest coordinated change is:

1. Resolve and document `trial_id` scope and whether start events are
   study-scoped or shared.
2. Add or update the versioned lifecycle event contract and TypeScript type
   according to the approved event name and payload.
3. Version the geometry snapshot contract if required study scope is approved,
   then update the P1 geometry producer and P3 mapping interface through the
   affected-owner process.
4. Add proposal-derived event and geometry fixtures plus contract tests,
   including exact retry, late arrival, missing start, wrong-study snapshot,
   and duplicate/conflicting behavior.
5. Approve the metric missingness convention and update the integration freeze
   or linked contracts through the documented contract-change process.
6. Only then implement Slice V metric calculations and tests.

No schema, implementation, migration, API, or test changes are made by this
proposal.
