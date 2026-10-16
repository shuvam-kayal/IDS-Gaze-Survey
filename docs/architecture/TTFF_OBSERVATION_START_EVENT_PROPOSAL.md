# Proposal: TTFF observation-start event

Status: approved implementation decision record

This document records the approved smallest lifecycle addition needed to measure
time to first fixation (TTFF). The versioned contracts and implementation are
the authoritative artifacts; this document retains the rationale and ownership
decisions.

Approved decisions: `trial.exposure_started` is study-scoped with exactly one
`study_ids` entry; `trial_id` is unique within `(session_id, study_id)`; no
`exposure_id` is introduced; multi-study geometry uses GeometrySnapshot v2 with
required `study_id`; and metric values use the documented nullable per-metric
object convention.

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

Canonical event type: `trial.exposure_started`.

This name combines the existing freeze's phrasing (“trial/exposure start
event”) while retaining the established `trial_id` domain concept. Its v1
event-specific schema defines the required payload and study scope.

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

Approved resolution: define the start event as study-scoped and require exactly
one entry in its existing `study_ids` array. That selects the FeatureRecord's
`study_id` without adding a new field. The approved trial identity scope is
`(session_id, study_id, trial_id)`; P1 emits a distinct study-scoped start event
when the same participant-visible exposure is analyzed for more than one study.
P1 owns lifecycle emission, P2 owns study configuration, and P3 owns derived
FeatureRecord selection.

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

Approved contract resolution: add required `study_id` to GeometrySnapshot v2
(a required field is not a backward-compatible patch to the current
`additionalProperties: false` v1 schema). The mapping interface requires the
requested `study_id` and expected `aoi_set_version`, filtering by session,
study, version, and timestamp. P3 retains v1 compatibility for existing
single-study fixtures and uses v2 with explicit study/version filters for
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
session-level gaze reason in `quality.missingness`. The approved Slice V
convention is the following per-metric object inside the existing `features`
object; it remains compatible with the frozen FeatureRecord schema:

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

The metric reason codes are implementation-level values recorded in metric
objects and aggregate `quality.missingness`; they do not alter the frozen
standard camera/sample list in `INTEGRATION_FREEZE.md §8`. The null-versus-zero
semantics and reason provenance are now the approved FeatureRecord convention.

The same representation should be used consistently for dwell, revisits,
transitions, entropy, and scan paths when their input is absent or undefined.
The convention is implemented by P3 and remains subject to the ordinary P4
consumer limitations review; no additional schema field is required.

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

## Approval record and follow-up

The owner review approved the following implementation boundaries:

- P1: study-scoped trial lifecycle and `trial.exposure_started` emission.
- P2: study/config/AOI-set association and GeometrySnapshot v2 study scope.
- P3: TTFF input, late-event invalidation, metric metadata, and mapping
  filters.
- P4: nullable metric objects, reason codes, units, windows, and limitations.

The coordinated implementation changes are:

1. Add or update the versioned lifecycle event contract and TypeScript type
   according to the approved event name and payload.
2. Version the geometry snapshot contract and update the P3 mapping interface
   through the affected-owner process.
3. Add event and geometry fixtures plus contract tests,
   including exact retry, late arrival, missing start, wrong-study snapshot,
   and duplicate/conflicting behavior.
4. Implement Slice V metric calculations and tests.

The proposal itself is documentation; the approved implementation is recorded
in `trial-exposure-start.v1.schema.json`, `geometry-snapshot.v2.schema.json`,
their examples and contract tests, the study-aware Slice U mapper, and the P3
metric engine. No database migration, API endpoint, raw-video storage, or
provider change is part of this decision.
