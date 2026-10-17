import test from "node:test";
import assert from "node:assert/strict";

import { WebGazerAdapter, WEBGAZER_STATUS, WEBGAZER_VERSION } from "../src/webgazer-adapter.js";
import { createMockP1Scenario } from "../src/mock-p1-harness.js";

function mockApi({ beginError } = {}) {
  const calls = [];
  let listener = null;
  return {
    calls,
    saveDataAcrossSessions(value) { calls.push(["saveDataAcrossSessions", value]); return this; },
    setGazeListener(value) { calls.push(["setGazeListener"]); listener = value; return this; },
    clearGazeListener() { calls.push(["clearGazeListener"]); listener = null; return this; },
    async begin() { calls.push(["begin"]); if (beginError) throw beginError; },
    end() { calls.push(["end"]); },
    emit(prediction, elapsedTime) { listener?.(prediction, elapsedTime); },
  };
}

test("start requires explicit consent and isolates WebGazer API calls", async () => {
  const api = mockApi();
  const adapter = new WebGazerAdapter(api);
  await assert.rejects(() => adapter.start({ session_id: "s1", test_only: true, consent_granted: false, on_sample: () => {}, on_status: () => {} }), /consent/);
  const statuses = [];
  await adapter.start({ session_id: "s1", test_only: true, consent_granted: true, on_sample: () => {}, on_status: (s) => statuses.push(s) });
  assert.deepEqual(api.calls.slice(0, 3), [["saveDataAcrossSessions", false], ["setGazeListener"], ["begin"]]);
  assert.deepEqual(statuses, [WEBGAZER_STATUS.INITIALIZING, WEBGAZER_STATUS.READY]);
  adapter.stop();
  assert.deepEqual(statuses.at(-1), WEBGAZER_STATUS.STOPPED);
  assert.equal(api.calls.filter(([name]) => name === "setGazeListener").length, 1);
});

test("frozen external-stream input fails closed without opening or stopping P1's stream", async () => {
  const api = mockApi();
  let stoppedTracks = 0;
  const stream = { getTracks: () => [{ stop: () => { stoppedTracks += 1; } }] };
  const statuses = [];
  const adapter = new WebGazerAdapter(api);
  await assert.rejects(() => adapter.start({
    session_id: "s1",
    camera_stream: stream,
    initial_geometry: { schema_version: "1.0.0", snapshot_id: "g1" },
    on_sample: () => {},
    on_status: (status, reason) => statuses.push([status, reason]),
  }), /gaze\.external_stream_unsupported/);
  assert.deepEqual(statuses, [
    [WEBGAZER_STATUS.INITIALIZING, undefined],
    [WEBGAZER_STATUS.UNAVAILABLE, "gaze.external_stream_unsupported"],
  ]);
  assert.deepEqual(api.calls, []);
  assert.equal(stoppedTracks, 0);
  adapter.stop();
  assert.equal(stoppedTracks, 0);
});

test("non-test starts require the frozen stream and geometry inputs", async () => {
  const adapter = new WebGazerAdapter(mockApi());
  const callbacks = { on_sample: () => {}, on_status: () => {} };
  await assert.rejects(() => adapter.start({ session_id: "s1", ...callbacks }), /camera_stream/);
  await assert.rejects(() => adapter.start({
    session_id: "s1",
    camera_stream: { getTracks: () => [] },
    ...callbacks,
  }), /initial_geometry/);
});

test("predictions become ProviderSamples with viewport pixels and elapsed UTC time", async () => {
  const api = mockApi();
  const samples = [];
  const adapter = new WebGazerAdapter(api, { clock: () => 1_735_732_800_000, viewport: () => ({ width: 100, height: 200 }) });
  await adapter.start({ session_id: "s1", test_only: true, consent_granted: true, on_sample: (s) => samples.push(s), on_status: () => {} });
  api.emit({ x: 25, y: 50 }, 100);
  assert.deepEqual(samples[0], {
    schema_version: "1.0.0", provider: "webgazer", provider_version: WEBGAZER_VERSION,
    sample_id: "s1:webgazer:0", capture_time_ms: 100,
    occurred_at: "2025-01-01T12:00:00.100Z", x_px: 25, y_px: 50, valid: true,
    quality: { confidence: null, flags: ["gaze.calibration_unverified"] },
  });
});

test("viewport dimensions are read per prediction so resize changes are not stale", async () => {
  const api = mockApi();
  const samples = [];
  let viewport = { width: 100, height: 100 };
  const adapter = new WebGazerAdapter(api, { viewport: () => viewport });
  await adapter.start({ session_id: "s1", test_only: true, consent_granted: true, on_sample: (s) => samples.push(s), on_status: () => {} });
  api.emit({ x: 90, y: 90 }, 0);
  viewport = { width: 200, height: 200 };
  api.emit({ x: 150, y: 150 }, 1);
  assert.equal(samples[0].valid, true);
  assert.equal(samples[1].valid, true);
  assert.equal(samples[1].x_px, 150);
});

test("missing, malformed and out-of-bounds predictions remain invalid and never become zero", async () => {
  const api = mockApi();
  const samples = [];
  const adapter = new WebGazerAdapter(api, { clock: () => 1_735_732_800_000, viewport: () => ({ width: 100, height: 100 }) });
  await adapter.start({ session_id: "s1", test_only: true, consent_granted: true, on_sample: (s) => samples.push(s), on_status: () => {} });
  api.emit(null, 0);
  api.emit({ x: Number.NaN, y: 50 }, 1);
  api.emit({ x: 101, y: 50 }, 2);
  assert.equal(samples.every((sample) => sample.valid === false), true);
  assert.equal(samples.every((sample) => sample.x_px === null && sample.y_px === null), true);
  assert.equal(samples.every((sample) => sample.quality.confidence === null), true);
});

test("failed initialization reports unavailable and cleanup is idempotent", async () => {
  const api = mockApi({ beginError: new DOMException("denied", "NotAllowedError") });
  const statuses = [];
  const adapter = new WebGazerAdapter(api);
  await assert.rejects(() => adapter.start({ session_id: "s1", test_only: true, consent_granted: true, on_sample: () => {}, on_status: (s, r) => statuses.push([s, r]) }), /permission_denied/);
  adapter.stop();
  assert.deepEqual(statuses.at(-1), [WEBGAZER_STATUS.UNAVAILABLE, "gaze.permission_denied"]);
  assert.equal(api.calls.filter(([name]) => name === "end").length, 1);
});

test("mock-P1 harness is deterministic and explicitly test-only", () => {
  const first = createMockP1Scenario();
  const second = createMockP1Scenario();
  assert.deepEqual(first, second);
  assert.equal(first.test_only, true);
  assert.equal(first.studies.length, 2);
  assert.equal(first.session_bootstrap.eligible_studies.length, 2);
  assert.equal(first.geometry_snapshots.length, 2);
  assert.equal(first.interaction_events[0].schema_version, "1.0.0");
  assert.equal(first.survey_events[0].event_type, "survey.completed");
  assert.equal(JSON.stringify(first).includes("video"), false);
});
