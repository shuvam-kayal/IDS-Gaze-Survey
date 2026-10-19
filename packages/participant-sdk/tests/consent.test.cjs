const test = require("node:test");
const assert = require("node:assert/strict");

const policy = {
  research: { version: "research-policy-v3", text: "Research participation is optional." },
  camera: { version: "camera-policy-v2", text: "Camera gaze tracking is optional." , offered: true },
};
const fixedTime = new Date("2026-10-19T07:30:00.000Z");
const makeTimers = () => {
  let nextId = 0;
  const active = new Set();
  const cleared = [];
  return {
    active,
    cleared,
    setInterval(callback, ms) { const id = ++nextId; active.add(id); return id; },
    clearInterval(id) { active.delete(id); cleared.push(id); },
  };
};

test("research consent must persist before collection and camera choice is separately versioned", async () => {
  const { ConsentLifecycle } = await import("../src/consent-lifecycle.js");
  const records = [];
  const controller = new ConsentLifecycle({ policy, persistConsent: async (record) => records.push(record), flushWithdrawalAudit: async () => {}, clock: () => fixedTime });

  assert.equal(controller.canCollectResearch, false);
  assert.throws(() => controller.registerCollector(() => {}), /Research consent is required/);
  await controller.recordResearchConsent("accepted");
  assert.equal(controller.canCollectResearch, true);
  assert.equal(controller.canCaptureCamera, false);
  let mediaRequests = 0;
  await assert.rejects(controller.startCamera({
    sessionId: "session-before-camera-choice",
    mediaDevices: { getUserMedia: async () => { mediaRequests += 1; return { getTracks: () => [] }; } },
    provider: { start: async () => {}, stop() {} },
    initialGeometry: { schema_version: "1.0.0" },
    onSample() {},
  }), /Separate camera consent is required/);
  assert.equal(mediaRequests, 0);
  await controller.recordCameraConsent("declined");
  assert.equal(controller.canCollectResearch, true);
  assert.equal(controller.canCaptureCamera, false);
  assert.deepEqual(records, [
    { scope: "research_participation", decision: "accepted", policy_version: "research-policy-v3", occurred_at: fixedTime.toISOString() },
    { scope: "camera_gaze", decision: "declined", policy_version: "camera-policy-v2", occurred_at: fixedTime.toISOString() },
  ]);
  assert.equal(controller.snapshot().camera.decision, "declined");
});

test("declining research or failing secure consent persistence never enables collection", async () => {
  const { ConsentLifecycle } = await import("../src/consent-lifecycle.js");
  const declined = new ConsentLifecycle({ policy, persistConsent: async () => {}, clock: () => fixedTime });
  await declined.recordResearchConsent("declined");
  assert.equal(declined.canCollectResearch, false);
  assert.equal(declined.snapshot().research.decision, "declined");
  await assert.rejects(declined.recordCameraConsent("accepted"), /Research consent must be accepted first/);

  const unavailable = new ConsentLifecycle({ policy, persistConsent: async () => { throw new Error("storage unavailable"); }, flushWithdrawalAudit: async () => {}, clock: () => fixedTime });
  await assert.rejects(unavailable.recordResearchConsent("accepted"), /storage unavailable/);
  assert.equal(unavailable.canCollectResearch, false);
  assert.equal(unavailable.snapshot().research.decision, "unknown");
  assert.throws(() => unavailable.registerListener({ addEventListener() {}, removeEventListener() {} }, "click", () => {}), /Research consent is required/);

  const missingAudit = new ConsentLifecycle({ policy, persistConsent: async () => {}, clock: () => fixedTime });
  await assert.rejects(missingAudit.recordResearchConsent("accepted"), /withdrawal audit capability is required/);
  assert.equal(missingAudit.canCollectResearch, false);
});

test("withdrawal immediately stops camera tracks, provider, listeners, and timers, then flushes only audit", async () => {
  const { ConsentLifecycle } = await import("../src/consent-lifecycle.js");
  const timers = makeTimers();
  const calls = [];
  const records = [];
  const controller = new ConsentLifecycle({
    policy,
    persistConsent: async (record) => records.push(record),
    flushWithdrawalAudit: async () => { calls.push("withdrawal_audit"); },
    clock: () => fixedTime,
    timers,
  });
  await controller.recordResearchConsent("accepted");
  await controller.recordCameraConsent("accepted");

  let endedListener;
  const track = {
    stopped: false,
    stop() { this.stopped = true; calls.push("track_stop"); },
    addEventListener(_name, listener) { endedListener = listener; },
    removeEventListener() { endedListener = undefined; },
  };
  const stream = { getTracks: () => [track] };
  let providerInput;
  const provider = {
    async start(input) { providerInput = input; calls.push("provider_start"); },
    stop() { calls.push("provider_stop"); },
  };
  let deliveredSamples = 0;
  await controller.startCamera({
    sessionId: "session-after-consent",
    mediaDevices: { getUserMedia: async () => stream },
    provider,
    initialGeometry: { schema_version: "1.0.0" },
    onSample: () => { deliveredSamples += 1; },
  });
  providerInput.on_sample({ sample_id: "sample-1" });
  assert.equal(deliveredSamples, 1);

  let listenerAttached = false;
  const target = {
    addEventListener() { listenerAttached = true; },
    removeEventListener() { listenerAttached = false; calls.push("listener_remove"); },
  };
  controller.registerListener(target, "click", () => {});
  const timerId = controller.registerInterval(() => {}, 1000);
  assert.equal(timers.active.has(timerId), true);

  const withdrawal = controller.withdraw();
  assert.equal(track.stopped, true, "camera track stops before withdrawal resolves");
  assert.equal(listenerAttached, false);
  assert.equal(timers.active.size, 0);
  providerInput.on_sample({ sample_id: "sample-after-withdrawal" });
  assert.equal(deliveredSamples, 1, "provider samples are discarded after withdrawal");
  const result = await withdrawal;

  assert.equal(result.research.decision, "withdrawn");
  assert.equal(result.cleanup_complete, true);
  assert.equal(result.audit_status, "sent");
  assert.deepEqual(timers.cleared, [timerId]);
  assert.equal(calls.filter((call) => call === "provider_stop").length, 1);
  assert.equal(calls.filter((call) => call === "withdrawal_audit").length, 1);
  assert.ok(calls.indexOf("provider_stop") < calls.indexOf("withdrawal_audit"));
  assert.equal(records.length, 2, "withdrawal does not enter the consent or ordinary telemetry queue");
  assert.equal(await controller.withdraw().then((value) => value.audit_status), "sent");
  assert.equal(calls.filter((call) => call === "provider_stop").length, 1, "cleanup is idempotent");
});

test("camera failure keeps research participation available without gaze", async () => {
  const { ConsentLifecycle } = await import("../src/consent-lifecycle.js");
  const controller = new ConsentLifecycle({ policy, persistConsent: async () => {}, flushWithdrawalAudit: async () => {}, clock: () => fixedTime });
  await controller.recordResearchConsent("accepted");
  await controller.recordCameraConsent("accepted");
  const result = await controller.startCamera({
    sessionId: "session-camera-unavailable",
    mediaDevices: { getUserMedia: async () => { throw Object.assign(new Error("denied"), { name: "NotAllowedError" }); } },
    provider: { start: async () => {}, stop() {} },
    initialGeometry: { schema_version: "1.0.0" },
    onSample() {},
  });
  assert.deepEqual(result, { modality: "non_gaze_only", permission: "denied" });
  assert.equal(controller.canCollectResearch, true);
  assert.equal(controller.canCaptureCamera, false);
});

test("a camera permission prompt resolving after withdrawal cannot restart capture", async () => {
  const { ConsentLifecycle } = await import("../src/consent-lifecycle.js");
  const controller = new ConsentLifecycle({ policy, persistConsent: async () => {}, clock: () => fixedTime, flushWithdrawalAudit: async () => {} });
  await controller.recordResearchConsent("accepted");
  await controller.recordCameraConsent("accepted");
  let resolvePermission;
  let providerStarts = 0;
  const track = { stopped: false, stop() { this.stopped = true; } };
  const pendingCapture = controller.startCamera({
    sessionId: "session-permission-race",
    mediaDevices: { getUserMedia: () => new Promise((resolve) => { resolvePermission = resolve; }) },
    provider: { start: async () => { providerStarts += 1; }, stop() {} },
    initialGeometry: { schema_version: "1.0.0" },
    onSample() {},
  });
  await controller.withdraw();
  resolvePermission({ getTracks: () => [track] });
  await assert.rejects(pendingCapture, /Consent changed before camera capture started/);
  assert.equal(track.stopped, true);
  assert.equal(providerStarts, 0);
  assert.equal(controller.canCaptureCamera, false);
});

test("failed withdrawal audit can retry its dedicated sink without repeating cleanup", async () => {
  const { ConsentLifecycle } = await import("../src/consent-lifecycle.js");
  let auditAttempts = 0;
  let collectorStops = 0;
  const controller = new ConsentLifecycle({
    policy,
    persistConsent: async () => {},
    flushWithdrawalAudit: async () => {
      auditAttempts += 1;
      if (auditAttempts === 1) throw new Error("audit service unavailable");
    },
    clock: () => fixedTime,
  });
  await controller.recordResearchConsent("accepted");
  controller.registerCollector(() => { collectorStops += 1; });
  assert.equal((await controller.withdraw()).audit_status, "failed");
  assert.equal((await controller.withdraw()).audit_status, "sent");
  assert.equal(auditAttempts, 2);
  assert.equal(collectorStops, 1);
});

test("camera consent is omitted when the server policy does not offer camera capture", async () => {
  const { ConsentLifecycle } = await import("../src/consent-lifecycle.js");
  const controller = new ConsentLifecycle({
    policy: { ...policy, camera: { ...policy.camera, offered: false } },
    persistConsent: async () => {},
    flushWithdrawalAudit: async () => {},
    clock: () => fixedTime,
  });
  await controller.recordResearchConsent("accepted");
  assert.equal(controller.snapshot().camera.decision, "not_offered");
  await assert.rejects(controller.recordCameraConsent("accepted"), /not offered/);
  assert.equal(controller.canCollectResearch, true);
  assert.equal(controller.canCaptureCamera, false);
});
