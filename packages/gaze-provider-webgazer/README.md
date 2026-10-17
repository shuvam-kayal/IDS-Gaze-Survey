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

## Manual browser check (not performed here)

After the P1 bridge is approved, run the package from a secure origin
(`https://...` or `http://localhost`), call `createWebGazerAdapter()`, and
start it only after the consent UI resolves with `consent_granted: true`.
Observe `initializing` then `ready`, perform the approved calibration and
interaction sequence, verify ProviderSamples contain viewport-pixel values and
null confidence, call `stop()`, and verify `stopped` plus listener cleanup.
Repeat with denied permission and an interrupted stream; verify
`gaze.permission_denied` or `gaze.capture_interrupted` and a non-gaze-only
FeatureRecord. No manual browser test was performed as part of this change.
