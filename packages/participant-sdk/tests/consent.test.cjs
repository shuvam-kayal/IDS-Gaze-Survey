const test = require("node:test");
const assert = require("node:assert/strict");

const policy = {
  research: { version: "research-policy-v3", text: "Research participation is optional." },
  camera: { version: "camera-policy-v2", text: "Camera gaze tracking is optional.", offered: true },
};
const fixedTime = new Date("2026-10-19T07:30:00.000Z");

async function consented() {
  const { ConsentLifecycle } = await import("../src/consent-lifecycle.js");
  const controller = new ConsentLifecycle({ policy, persistConsent: async () => {}, flushWithdrawalAudit: async () => {}, clock: () => fixedTime });
  await controller.recordResearchConsent("accepted");
  await controller.recordCameraConsent("accepted");
  return controller;
}

function input(provider, overrides = {}) {
  return { sessionId: "session-camera", provider, initialGeometry: { schema_version: "1.0.0" }, onSample: () => {}, ...overrides };
}

test("research consent and separate camera consent gate provider startup", async () => {
  const { ConsentLifecycle } = await import("../src/consent-lifecycle.js");
  let starts = 0;
  const provider = { start: async () => { starts += 1; }, stop() {} };
  const controller = new ConsentLifecycle({ policy, persistConsent: async () => {}, flushWithdrawalAudit: async () => {}, clock: () => fixedTime });
  await assert.rejects(controller.startCamera(input(provider)), /Research consent is required/);
  await controller.recordResearchConsent("accepted");
  await assert.rejects(controller.startCamera(input(provider)), /Separate camera consent/);
  assert.equal(starts, 0);
  await controller.recordCameraConsent("accepted");
  await controller.startCamera(input(provider));
  assert.equal(starts, 1);
});

test("provider receives the frozen consent-gated input and no camera stream", async () => {
  const controller = await consented();
  let received;
  const provider = { async start(value) { received = value; value.on_status("ready"); }, stop() {} };
  await controller.startCamera(input(provider, { sessionId: "session-contract", initialGeometry: { snapshot_id: "geometry-1" } }));
  assert.deepEqual(Object.keys(received).sort(), ["consent_granted", "initial_geometry", "on_sample", "on_status", "session_id"]);
  assert.equal(received.session_id, "session-contract");
  assert.equal(received.consent_granted, true);
  assert.equal(received.camera_source, undefined);
  assert.equal(received.camera_stream, undefined);
  assert.equal(controller.snapshot().camera.status, "active");
});

test("stopping camera capture does not withdraw the participant session", async () => {
  const controller = await consented();
  let stops = 0;
  const provider = { async start(value) { value.on_status("ready"); }, stop() { stops += 1; } };
  await controller.startCamera(input(provider));
  await controller.stopCamera();
  assert.equal(stops, 1);
  assert.equal(controller.snapshot().withdrawal.withdrawn, false);
  assert.equal(controller.canCollectResearch, true);
});

test("provider permission denial preserves research and explicit non-gaze fallback", async () => {
  const controller = await consented();
  const statuses = [];
  const result = await controller.startCamera(input({
    async start(value) { value.on_status("unavailable", "gaze.permission_denied"); throw Object.assign(new Error("denied"), { name: "NotAllowedError" }); },
    stop() {},
  }, { onCameraStatus: (value) => statuses.push(value) }));
  assert.equal(result.modality, "non_gaze_only");
  assert.equal(result.permission, "denied");
  assert.equal(result.status, "denied");
  assert.equal(result.reason, "gaze.permission_denied");
  assert.equal(controller.canCollectResearch, true);
  assert.equal(controller.canCaptureCamera, false);
  assert.equal(statuses.at(-1).reason, "gaze.permission_denied");
});

test("provider startup failure is not represented as active", async () => {
  const controller = await consented();
  let stops = 0;
  const result = await controller.startCamera(input({ async start() { throw new Error("provider unavailable"); }, stop() { stops += 1; } }));
  assert.equal(result.status, "provider_failed");
  assert.equal(result.modality, "non_gaze_only");
  assert.equal(result.reason, "gaze.provider_failure");
  assert.equal(controller.canCaptureCamera, false);
  assert.equal(stops, 1);
});

test("ready samples are accepted, stop is idempotent, and late samples are ignored", async () => {
  const controller = await consented();
  let callbacks;
  let stops = 0;
  let delivered = 0;
  const provider = { async start(value) { callbacks = value; value.on_status("ready"); }, stop() { stops += 1; } };
  await controller.startCamera(input(provider, { onSample: () => { delivered += 1; } }));
  callbacks.on_sample({ sample_id: "before-stop" });
  assert.equal(delivered, 1);
  controller.stopProvider();
  controller.stopProvider();
  callbacks.on_sample({ sample_id: "after-stop" });
  callbacks.on_status("ready");
  assert.equal(delivered, 1);
  assert.equal(stops, 1);
  assert.equal(controller.canCaptureCamera, false);
});

test("withdrawal during pending startup stops the provider and rejects late startup", async () => {
  const controller = await consented();
  let resolveStart;
  let stops = 0;
  let callbacks;
  const pending = controller.startCamera(input({
    start(value) { callbacks = value; return new Promise((resolve) => { resolveStart = resolve; }); },
    stop() { stops += 1; },
  }));
  await controller.withdraw();
  resolveStart();
  await assert.rejects(pending, /withdrawn|Consent/);
  callbacks.on_status("ready");
  callbacks.on_sample({ sample_id: "late" });
  assert.equal(stops, 1);
  assert.equal(controller.canCaptureCamera, false);
  assert.equal(controller.snapshot().withdrawal.withdrawn, true);
});

test("withdrawal prevents callbacks and never stops a foreign stream", async () => {
  const controller = await consented();
  let callbacks;
  let stops = 0;
  let delivered = 0;
  const provider = { async start(value) { callbacks = value; value.on_status("ready"); }, stop() { stops += 1; } };
  await controller.startCamera(input(provider, { onSample: () => { delivered += 1; } }));
  const foreignTrack = { stopped: false, stop() { this.stopped = true; } };
  await controller.withdraw();
  callbacks.on_sample({ sample_id: "after-withdrawal" });
  assert.equal(delivered, 0);
  assert.equal(stops, 1);
  assert.equal(foreignTrack.stopped, false);
  await controller.shutdown();
  assert.equal(stops, 1);
});

test("provider stopped status becomes interrupted non-gaze state", async () => {
  const controller = await consented();
  let callbacks;
  const provider = { async start(value) { callbacks = value; value.on_status("ready"); }, stop() {} };
  await controller.startCamera(input(provider));
  callbacks.on_status("stopped", "gaze.capture_interrupted");
  assert.equal(controller.snapshot().camera.status, "interrupted");
  assert.equal(controller.snapshot().camera.missingness, "gaze.capture_interrupted");
  assert.equal(controller.canCaptureCamera, false);
});

test("declined research or unavailable consent persistence never enables collection", async () => {
  const { ConsentLifecycle } = await import("../src/consent-lifecycle.js");
  const declined = new ConsentLifecycle({ policy, persistConsent: async () => {}, clock: () => fixedTime });
  await declined.recordResearchConsent("declined");
  assert.equal(declined.canCollectResearch, false);
  const unavailable = new ConsentLifecycle({ policy, persistConsent: async () => { throw new Error("storage unavailable"); }, flushWithdrawalAudit: async () => {}, clock: () => fixedTime });
  await assert.rejects(unavailable.recordResearchConsent("accepted"), /storage unavailable/);
  assert.equal(unavailable.canCollectResearch, false);
});

test("camera consent is omitted when policy does not offer camera capture", async () => {
  const { ConsentLifecycle } = await import("../src/consent-lifecycle.js");
  const controller = new ConsentLifecycle({ policy: { ...policy, camera: { ...policy.camera, offered: false } }, persistConsent: async () => {}, flushWithdrawalAudit: async () => {}, clock: () => fixedTime });
  await controller.recordResearchConsent("accepted");
  await assert.rejects(controller.recordCameraConsent("accepted"), /not offered/);
  assert.equal(controller.snapshot().camera.decision, "not_offered");
});
