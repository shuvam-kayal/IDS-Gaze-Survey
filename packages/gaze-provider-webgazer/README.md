# P3 WebGazer provider boundary

This package is the P3-owned browser-side adapter boundary for the exact
`webgazer@3.5.3` npm dependency. It emits only the frozen `ProviderSample`
shape. Provider-native objects, webcam frames, and error objects are not
returned to callers or included in samples.

WebGazer 3.5.3 is the final planned official release and official maintenance
is no longer guaranteed; community support continues through GitHub Issues.
The package declares WebGazer's `GPL-3.0-or-later` license. The repository's
overall license is unchanged. Legal review is required before distributing a
production bundle, including assessment of the upstream project's stated
licensing alternatives.

The adapter calls `saveDataAcrossSessions(false)` before `begin()` so learned
calibration data is not intentionally carried between sessions. It starts
only when the caller supplies `consent_granted: true`; camera denial or
initialization failure produces a reason-coded unavailable status. WebGazer
prediction coordinates are viewport-relative pixels, and each callback reads
the current viewport dimensions. Null, non-finite, and out-of-bounds
predictions remain invalid with null coordinates. Confidence remains null
because the documented prediction callback does not provide a confidence
score. Under the existing P3 quality boundary, a sequence with otherwise
valid predictions but no confidence is therefore marked low quality and does
not produce gaze metrics; this is intentional missingness, not a fabricated
confidence or measured zero.

## Frozen-interface limitation

The frozen TypeScript interface requires P1 to provide a consented
`MediaStream`, while WebGazer's public `begin()` API acquires the camera
itself. This adapter therefore uses explicit caller consent as a start gate,
but does not claim that it consumes the future P1-supplied stream. P1 and the
integrator must approve a bridge decision before production wiring: either
authorize WebGazer's post-consent acquisition or add a supported stream-injection
interface. No frozen contract was changed here.

## Test-only mock-P1 harness

`src/mock-p1-harness.js` creates deterministic, explicitly `test_only` session,
two-study trial, AOI-version, interaction, survey, viewport, consent, and
prediction inputs. It never accesses a webcam and must not be used as
participant data.

## Manual browser smoke test

This is a provider-only smoke test, not the final P1 integration. It uses the
real locally installed WebGazer package and requests the webcam only after the
checkbox and button are used. It does not send data to the server or persist
diagnostic samples.

From PowerShell at the repository root:

```powershell
cd C:\Projects\IDS-Gaze-Survey
npm install --prefix .\packages\gaze-provider-webgazer --include=dev
npm run build:smoke --prefix .\packages\gaze-provider-webgazer
npm run serve:smoke --prefix .\packages\gaze-provider-webgazer
```

Keep that terminal running, then open `http://localhost:4173/` in a supported
browser. `localhost` is the secure browser origin used for this local test.
When finished, return to the server terminal and press `Ctrl+C`. The build
bundles the installed `webgazer@3.5.3` and copies its pinned local FaceMesh
runtime assets into the smoke-test directory; it does not use a CDN or mock
API. The package test also starts the local server and checks that each copied
runtime asset returns HTTP 200.

Manual cases and pass observations:

1. Leave the checkbox clear and press Start: capture remains stopped and the
   status says consent is required.
2. Check the consent box and press Start, then grant camera permission: status
   progresses through `initializing` to `ready`; temporary sample count grows.
3. For valid predictions, the diagnostic line shows finite viewport-pixel
   coordinates, `confidence=null`, and no video/frame data is displayed or
   transmitted.
4. Deny the browser permission: status becomes unavailable with
   `gaze.permission_denied`; no uncaught page error or capture loop remains.
5. If the provider emits null/invalid predictions, samples remain invalid with
   null coordinates and reason flags; `(0, 0)` is not a valid missing-value
   substitute.
6. Resize the browser while running: the displayed viewport changes and later
   predictions continue using the new dimensions.
7. Press Stop: the status becomes stopped, the count stops increasing, and a
   second Stop does not create another listener or error.

WebGazer startup is not proof of accurate gaze tracking or successful
calibration. The current callback provides no per-sample confidence, so
confidence remains null and the existing P3 quality boundary may mark the
capture low quality. No manual browser test was performed as part of this
change.

## WebGazer 3.5.3 implementation notes

These notes are based on the installed source under
`node_modules/webgazer/src/` (the package is pinned to `3.5.3`), especially
`index.mjs`, `facemesh.mjs`, `params.mjs`, and the installed README. They are
provider facts, not claims that this smoke page has measured accuracy.

- `begin()` calls `navigator.mediaDevices.getUserMedia()` and then initializes
  the video, FaceMesh tracker, prediction loop, and UI. It does not run a
  separate automatic nine-point calibration procedure.
- The loop calls the function registered by `setGazeListener(listener)` on
  every prediction cycle. The callback receives `(prediction, elapsedTime)`;
  `prediction` can be `null` when no usable tracker prediction is available.
  The P3 adapter preserves that as an invalid sample with explicit missingness.
- `init()` calls the internal `addMouseEventListeners()` automatically. The
  public method exists, but this smoke page does not need to call it a second
  time. Clicks and throttled mouse moves call `recordScreenPosition()` and add
  training data to the active regression when eye features are available.
- The default installed model is the `TFFaceMesh` tracker with the `ridge`
  regression model. The regression is updated by those click/move training
  observations. The default Kalman smoothing setting is separate from
  calibration/training.
- `saveDataAcrossSessions(false)` disables loading prior global data during
  `begin()` and prevents click data from being written to the cross-session
  store. It does not disable training during the current page session.
- The built-in red point is controlled by `showPredictionPoints(true/false)`.
  The source places it using a smoothed recent-prediction value and bounds it
  to the viewport, so it is not a direct visualization of the raw callback
  value. The smoke page disables that overlay and shows a separate green
  marker driven only by the adapter callback.
- WebGazer exposes `isReady()` for initialization state, but the inspected
  source provides no validated calibration-success or per-sample accuracy
  signal. The guided page therefore reports only `camera ready`,
  `calibrating`, `capturing predictions`, and `calibration procedure
  completed; accuracy not yet validated`.

The guided procedure uses nine viewport-relative targets (corners, edge
centers, and center) and three deliberate clicks per target. Three clicks is a
repeatability choice for this manual diagnostic, not a WebGazer-required
threshold and not an accuracy criterion. The target clicks provide the
mouse/click training observations described above; they do not prove that
eye-only predictions are accurate.

Manual comparison procedure:

1. Rebuild and serve the page, check consent, and press Start. Grant camera
   permission. Before clicking any calibration target, move the mouse away and
   leave it stationary for at least one second. Record the callback counts,
   null count, finite count, and green-marker behavior while looking at several
   positions. This is the pre-procedure qualitative observation.
2. For each blue target, look directly at it and click it three times. Wait
   for the next target after each set. The page reports `calibrating` and the
   current target progress.
3. After all nine targets, the page reports `capturing predictions` and
   `calibration procedure completed; accuracy not yet validated`. Move the
   mouse away, leave it stationary again, and look at several positions.
4. Compare the green callback marker and finite/null counters with the first
   observation. Do not use the browser cursor, target location, or a changing
   non-null coordinate as an accuracy measurement. Restart calibration to
   repeat the procedure, or press Stop to verify cleanup.
