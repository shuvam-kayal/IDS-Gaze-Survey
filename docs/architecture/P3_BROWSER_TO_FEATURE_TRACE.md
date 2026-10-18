# P3 Browser-to-FeatureRecord Trace

This note records the current repository boundary. It does not claim that the
local WebGazer smoke page is a browser-to-backend end-to-end test.

## Verified processing path

1. `packages/gaze-provider-webgazer/src/webgazer-adapter.js` wraps the pinned
   WebGazer API. Its callback emits only the ProviderSample v1 shape: pixel
   coordinates, monotonic capture time, UTC `occurred_at`, nullable confidence,
   and quality flags. The smoke page's `on_sample` callback currently displays
   these samples locally; it does not send them to an application endpoint.
2. `services/gaze_engine/adapter.py::ProviderSampleAdapter.normalize_batch`
   validates the provider shape, viewport bounds, timestamps and sample
   identities, then converts pixels to canonical `viewport_normalized`
   GazeRecords. It sorts deterministically by occurrence timestamp and sample
   ID. Missing coordinates remain missing; out-of-viewport coordinates are
   rejected.
3. `services/gaze_engine/quality.py::evaluate_gaze_quality` validates the
   canonical records. WebGazer's `confidence: null` and
   `gaze.calibration_unverified` are preserved. Missing confidence causes the
   existing `gaze.low_quality` result when otherwise valid samples meet the
   sample-count thresholds; it does not fabricate confidence or change sample
   validity.
4. `services/feature_engine/gaze_pipeline.py::process_trial_gaze` creates the
   explicit study/trial/window association, validates it, maps fixations to
   the pinned study/AOI-set geometry, computes metrics, and calls the existing
   FeatureRecord builder. `process_session_gaze` applies SessionBootstrap
   study/config/AOI pinning and deterministic multi-study isolation.
5. `process_persisted_session_gaze` retrieves validated EventEnvelopes through
   the existing telemetry repository. Provider samples remain structured
   inputs to the P3 processing call; raw video is not accepted or persisted.

The integration test in `tests/test_gaze_pipeline.py` validates the existing
WebGazer-shaped fixture against ProviderSample v1, normalizes it through the
real adapter, validates the resulting GazeRecords, and then runs the real
trial pipeline to a schema-valid FeatureRecord. It is deterministic fixture
evidence, not evidence that a webcam browser session reached Python.

## Current browser-to-backend gap

No current P1/API interface accepts the smoke page's ProviderSample callback.
The smoke server serves the page and local WebGazer assets only. There is no
approved endpoint or browser transport in this repository that binds those
samples to a server-side `session_id`, study/trial lifecycle, viewport
geometry snapshot, and telemetry identity.

The existing telemetry interface is the P3-owned
`services/telemetry/ingestion.py` validation/deduplication boundary and its
PostgreSQL repository in `services/telemetry/persistence.py`. It accepts
EventEnvelope records, not an undocumented browser gaze payload. The existing
P3 feature path accepts provider samples as an explicit in-process
`process_trial_gaze` input and requires a validated
`TrialObservationContext`, pinned AOI-set version, geometry snapshot, and
trial lifecycle start event.

The revised architecture in `docs/architecture/INTEGRATION_FREEZE.md` §9
keeps consent and participant lifecycle in P1, while allowing a selected P3
provider to acquire and release its own camera stream through the supported
provider API. P1 supplies `consent_granted: true`, initial geometry, and
lifecycle callbacks; it does not supply a mandatory `MediaStream`.

## WebGazer 3.5.3 stream investigation

The installed `node_modules/webgazer/src/index.mjs` provides the following
source evidence:

- Private `init(stream)` stores the argument in WebGazer's internal
  `videoStream`, creates a video element, and assigns `videoElement.srcObject =
  stream`.
- Public `begin()` does not accept a stream argument. Unless static-video debug
  mode is selected, it calls `navigator.mediaDevices.getUserMedia(...)` and
  passes the newly obtained stream to private `init(stream)`.
- Public `setVideoElementCanvas()` accepts a canvas, not a MediaStream. Public
  `setStaticVideo()` accepts a video location for debug use, not an already
  consented camera stream.
- Public `end()` removes WebGazer DOM elements and pauses the loop, but the
  source comments out `stopVideo()`. Public `stopVideo()` directly calls
  `videoStream.getTracks()[0].stop()` and is therefore unsafe to call on a
  stream owned by P1.

There is consequently no verified public external-stream initialization path
in the pinned package. Passing a stream through private `init()` would require
bundler/runtime-specific access to a non-exported function and would be
brittle across package updates. The provider now uses public `begin()` after
the explicit consent authorization and calls provider cleanup in an order that
releases the stream acquired by WebGazer. It rejects legacy external-stream
inputs rather than silently accepting them.

The approved design is the third option: WebGazer owns acquisition for this
provider, while P1 remains responsible for consent authorization and the
participant-facing lifecycle. A future provider that requires an external
stream must be reviewed against this lifecycle before selection.

## Existing identity and lifecycle behavior

- Provider samples use `sample_id` within a session/provider capture stream;
  duplicate sample IDs are rejected by normalization.
- Event delivery uses the existing `(session_id, event_id)` identity and
  exact-retry/conflicting-payload behavior in telemetry persistence.
- Trial processing requires `(session_id, study_id, trial_id,
  aoi_set_version)` and a start-inclusive/end-exclusive observation window.
  Samples outside the window are rejected and empty qualifying observations
  remain missing rather than becoming zero.
- Late persisted events follow the existing repository/session-processing
  behavior; they are not invented by the smoke page.
- Camera denial, interruption, or empty gaze bypasses provider metrics while
  preserving the existing non-gaze FeatureRecord path with reason-coded
  missingness.

## Ownership and smallest next step

P3 can maintain the provider adapter, normalization, quality, fixtures, and
processing tests. P1 owns consent, camera tracks, browser event buffering,
trial/survey lifecycle, and the narrow browser bridge. API and transport
wiring is a shared/integrator boundary and must not be added by this slice.

The smallest compliant next step is an owner-approved P1/integrator contract
test for the browser bridge. It should provide one consented stream/lifecycle
context and one ProviderSample batch (or an explicitly approved streaming
transport) with session, study/trial, geometry snapshot, and retry semantics.
P3 can then connect that approved transport to the existing normalizer and
`process_session_gaze` path without adding a competing endpoint or changing
the frozen ProviderSample/GazeRecord contracts.
