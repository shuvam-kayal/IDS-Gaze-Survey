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
bundles the installed `webgazer@3.5.3`; it does not use a CDN or mock API.

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
