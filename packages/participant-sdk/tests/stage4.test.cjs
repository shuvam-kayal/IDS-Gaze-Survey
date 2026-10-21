const test = require("node:test");
const assert = require("node:assert/strict");

const questionConfig = {
  schema_version: "1.0.0", study_id: "study-a", question_set_version: "questions-v8",
  questions: [
    { question_id: "single", prompt: "Choose one", answer_type: "single_choice", required: true, order: 0, options: [{ option_id: "a", label: "Alpha" }, { option_id: "b", label: "Beta" }] },
    { question_id: "multi", prompt: "Choose several", answer_type: "multi_choice", required: true, order: 1, options: [{ option_id: "x", label: "X" }, { option_id: "y", label: "Y" }] },
    { question_id: "rating", prompt: "Rate it", answer_type: "scale", required: true, order: 2, options: [{ option_id: "1", label: "Low" }, { option_id: "5", label: "High" }] },
    { question_id: "yes", prompt: "Would return?", answer_type: "boolean", required: true, order: 3 },
    { question_id: "comment", prompt: "Optional comment", answer_type: "free_text", required: false, order: 4 },
  ],
};
const surveyPlan = { schema_version: "1.0.0", survey_plan_id: "plan-1", session_id: "session-1", study_ids: ["study-a"], question_ids: ["single", "multi", "rating", "yes", "comment"], presentation: "end_of_session" };
const context = { experience_id: "experience-1", session_id: "session-1", participant_id: null };
const consentController = { canCollectResearch: true, registerCollector: () => () => true };

test("versioned question fixtures cover choice, multiple choice, scale, boolean, free text and optional answers", async () => {
  const { parseQuestionConfig, createSurveyRuntime } = await import("../src/survey.js");
  const parsed = parseQuestionConfig(questionConfig);
  assert.equal(parsed.question_set_version, "questions-v8");
  assert.deepEqual(parsed.questions.map((question) => question.answer_type), ["single_choice", "multi_choice", "scale", "boolean", "free_text"]);
  let submitted;
  const runtime = createSurveyRuntime({ questionConfigs: [questionConfig], surveyPlan, context, consentController, onSubmit: (payload) => { submitted = payload; } });
  runtime.setAnswer("single", "b");
  runtime.setAnswer("multi", ["y", "x"]);
  runtime.setAnswer("rating", "5");
  runtime.setAnswer("yes", true);
  await runtime.submit();
  assert.deepEqual(submitted.responses.map(({ question_id }) => question_id), ["single", "multi", "rating", "yes"]);
  assert.deepEqual(submitted.responses[1].answer, ["y", "x"], "selection order is preserved");
  assert.equal(submitted.responses[0].question_set_version, "questions-v8");
  assert.equal(submitted.responses[0].study_id, "study-a");
  assert.equal(runtime.state, "complete");
});

test("survey enforces required answers, option/range membership and strict contracts", async () => {
  const { parseQuestionConfig, createSurveyRuntime } = await import("../src/survey.js");
  assert.throws(() => parseQuestionConfig({ ...questionConfig, schema_version: "2.0.0" }), /Unsupported QuestionConfig/);
  assert.throws(() => parseQuestionConfig({ ...questionConfig, questions: [{ ...questionConfig.questions[0], extra: "not allowed" }] }), /not supported/);
  assert.throws(() => parseQuestionConfig({ ...questionConfig, questions: [{ ...questionConfig.questions[2], options: undefined }] }), /versioned options/);
  const runtime = createSurveyRuntime({ questionConfigs: [questionConfig], surveyPlan, context, consentController, onSubmit() {} });
  await assert.rejects(runtime.submit(), (error) => error.missing_question_ids.includes("single") && error.missing_question_ids.includes("yes"));
  assert.throws(() => runtime.setAnswer("single", "out-of-range"), /configured option/);
  assert.throws(() => runtime.setAnswer("multi", ["x", "x"]), /unique configured option/);
  assert.throws(() => runtime.setAnswer("rating", "3"), /configured option/);
  assert.throws(() => createSurveyRuntime({ questionConfigs: [questionConfig], surveyPlan: { ...surveyPlan, session_id: "wrong" }, context, consentController, onSubmit() {} }), /this session/);
});

test("submission retry reuses frozen payload, submission ID and response IDs", async () => {
  const { createSurveyRuntime } = await import("../src/survey.js");
  let nextId = 0;
  let attempts = 0;
  const payloads = [];
  const runtime = createSurveyRuntime({
    questionConfigs: [questionConfig], surveyPlan, context, consentController, idFactory: () => `id-${++nextId}`,
    onSubmit: async (payload) => { attempts += 1; payloads.push(payload); if (attempts === 1) throw new Error("temporary network failure"); return { accepted: true }; },
  });
  runtime.setAnswer("single", "a");
  runtime.setAnswer("multi", ["x"]);
  runtime.setAnswer("rating", "1");
  runtime.setAnswer("yes", false);
  await assert.rejects(runtime.submit(), /temporary network failure/);
  assert.equal(runtime.state, "retryable");
  const payload = runtime.getPayloadForRetry();
  assert.throws(() => runtime.setAnswer("single", "b"), /locked/);
  assert.deepEqual(await runtime.submit(), { accepted: true });
  assert.equal(payloads[0], payloads[1]);
  assert.equal(payload.submission_id, "id-1");
  assert.equal(payload.responses[0].response_id, "id-2");
  assert.equal(payload.responses[0].submission_id, payload.submission_id);
  assert.equal(nextId, 5);
});

test("survey collection is consent-gated and withdrawal aborts in-flight submission state", async () => {
  const { createSurveyRuntime } = await import("../src/survey.js");
  let allowed = false;
  let registeredStop;
  const controller = { get canCollectResearch() { return allowed; }, registerCollector(stop) { registeredStop = stop; return () => true; } };
  const runtime = createSurveyRuntime({ questionConfigs: [questionConfig], surveyPlan, context, consentController: controller, onSubmit: (_payload, { signal }) => new Promise((resolve, reject) => {
    signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
  }) });
  assert.throws(() => runtime.setAnswer("single", "a"), /not active/);
  await assert.rejects(runtime.submit(), /not active/);
  allowed = true;
  runtime.setAnswer("single", "a");
  runtime.setAnswer("multi", ["x"]);
  runtime.setAnswer("rating", "1");
  runtime.setAnswer("yes", true);
  const submission = runtime.submit();
  await Promise.resolve();
  allowed = false;
  registeredStop();
  await assert.rejects(submission, /aborted|withdrawal/);
  assert.equal(runtime.state, "stopped");
  assert.equal(runtime.getAnswer("single"), undefined);
  assert.equal(runtime.getPayloadForRetry(), null);
});

test("withdrawal between submit and network dispatch prevents the request from starting", async () => {
  const { createSurveyRuntime } = await import("../src/survey.js");
  let allowed = true;
  let registeredStop;
  let calls = 0;
  const controller = { get canCollectResearch() { return allowed; }, registerCollector(stop) { registeredStop = stop; return () => true; } };
  const runtime = createSurveyRuntime({ questionConfigs: [questionConfig], surveyPlan, context, consentController: controller, onSubmit: () => { calls += 1; } });
  runtime.setAnswer("single", "a");
  runtime.setAnswer("multi", ["x"]);
  runtime.setAnswer("rating", "1");
  runtime.setAnswer("yes", false);
  const pending = runtime.submit();
  allowed = false;
  registeredStop();
  await assert.rejects(pending, /stopped before collection/);
  assert.equal(calls, 0);
  assert.equal(runtime.state, "stopped");
});

class FakeTarget {
  constructor() { this.listeners = new Map(); }
  addEventListener(name, listener) { const listeners = this.listeners.get(name) || new Set(); listeners.add(listener); this.listeners.set(name, listeners); }
  removeEventListener(name, listener) { this.listeners.get(name)?.delete(listener); }
  fire(name, event = {}) { for (const listener of this.listeners.get(name) || []) listener(event); }
}

test("interaction telemetry excludes forms and page content and emits only the policy allow-list", async () => {
  const { startInteractionCapture } = await import("../src/interactions.js");
  const doc = new FakeTarget();
  doc.visibilityState = "visible";
  const win = new FakeTarget();
  win.scrollX = 12;
  win.scrollY = 345;
  const stopped = [];
  const controller = {
    registerListener(target, name, listener) { target.addEventListener(name, listener); const stop = () => target.removeEventListener(name, listener); stopped.push(stop); return () => true; },
    registerCollector(stop) { stopped.push(stop); return () => true; },
  };
  const events = [];
  let aoiLookups = 0;
  let resolvedAoi = "aoi-card";
  const capture = startInteractionCapture({
    context: { experience_id: "experience-1", study_ids: ["study-a"], session_id: "session-1" },
    policy: { version: "interactions-v2", allowed_event_types: ["interaction.click", "interaction.hover", "interaction.scroll", "interaction.navigation", "page.visibility_changed"] },
    controller, document: doc, window: win, onEvent: (event) => events.push(event), allowedAoiIds: ["aoi-card"], eventId: () => `event-${events.length + 1}`, wallClock: () => new Date("2026-04-05T06:07:08.000Z"),
    resolveAoiId: () => { aoiLookups += 1; return resolvedAoi; },
  });
  const pageTextTarget = { value: "never capture me", innerText: "private page copy", closest: () => null };
  doc.fire("click", { target: pageTextTarget, clientX: 1, clientY: 2 });
  const formInput = { value: "hunter2-secret", closest: (selector) => selector.includes("form") ? {} : null };
  doc.fire("click", { target: formInput, clientX: 5, clientY: 6 });
  assert.equal(aoiLookups, 1, "sensitive controls are rejected before AOI resolution");
  resolvedAoi = "page content that is not a configured AOI";
  doc.fire("click", { target: pageTextTarget, clientX: 3, clientY: 4 });
  win.fire("scroll");
  doc.visibilityState = "hidden";
  doc.fire("visibilitychange");
  capture.recordNavigation();
  assert.deepEqual(events.map((event) => event.event_type), ["interaction.click", "interaction.click", "interaction.scroll", "page.visibility_changed", "interaction.navigation"]);
  assert.deepEqual(events[0].payload, { x_px: 1, y_px: 2, target_aoi_id: "aoi-card" });
  assert.deepEqual(events[1].payload, { x_px: 3, y_px: 4 }, "unconfigured AOI resolver output is excluded");
  assert.deepEqual(events[2].payload, { scroll_x_px: 12, scroll_y_px: 345 });
  assert.deepEqual(events[3].payload, { visibility_state: "hidden" });
  assert.deepEqual(events[4].payload, {} , "route URLs and page content are omitted");
  const serialized = JSON.stringify(events);
  assert.equal(serialized.includes("hunter2-secret"), false);
  assert.equal(serialized.includes("private page copy"), false);
  capture.stop();
  doc.fire("click", { target: pageTextTarget, clientX: 1, clientY: 2 });
  assert.equal(events.length, 5);
});

test("trial timing uses monotonic elapsed time, UTC envelopes, visibility pauses and one terminal event", async () => {
  const { TrialLifecycle } = await import("../src/trial-lifecycle.js");
  let now = 100;
  let wall = new Date("2026-07-08T09:10:11.000Z");
  const events = [];
  const scheduled = new Map();
  let nextTimer = 0;
  const consentController = { canCollectResearch: true, registerCollector: () => () => true };
  const timers = {
    setTimeout(callback, delay) { const id = ++nextTimer; scheduled.set(id, { callback, delay }); return id; },
    clearTimeout(id) { scheduled.delete(id); },
  };
  const lifecycle = new TrialLifecycle({
    context: { experience_id: "exp-1", session_id: "session-1", study_id: "study-a", participant_id: null },
    timingRules: { version: "timing-v3", duration_ms: 1000, pause_on_hidden: true },
    onEvent: (event) => events.push(event), monotonicNow: () => now, wallClock: () => wall,
    eventId: (() => { let n = 0; return () => `event-${++n}`; })(), timers, consentController,
  });
  lifecycle.start("trial-1");
  assert.equal(events[0].event_type, "trial.exposure_started");
  assert.equal(events[0].occurred_at, "2026-07-08T09:10:11.000Z");
  assert.deepEqual(Object.keys(events[0].payload), ["trial_id"]);
  now = 500;
  lifecycle.handleVisibility(true);
  assert.equal(lifecycle.state, "paused");
  assert.equal(lifecycle.snapshot().elapsed_ms, 400);
  now = 9500;
  lifecycle.handleVisibility(false);
  assert.equal(lifecycle.state, "active");
  assert.equal(lifecycle.snapshot().elapsed_ms, 400, "hidden time is excluded by the pinned timing policy");
  now = 10100;
  const timer = [...scheduled.values()][0];
  assert.equal(timer.delay, 600);
  wall = new Date("2026-07-08T09:10:12.000Z");
  timer.callback();
  assert.equal(lifecycle.state, "completed");
  assert.equal(events.filter((event) => event.event_type === "trial.exposure_ended").length, 1);
  assert.equal(events.at(-1).occurred_at, "2026-07-08T09:10:12.000Z");
  assert.equal(lifecycle.abort(), false, "terminal state cannot transition twice");
  assert.equal(lifecycle.skip(), false);
  assert.equal(events.length, 2);
});

test("trial lifecycle honors continue-on-hidden timing and aborts navigation once", async () => {
  const { TrialLifecycle } = await import("../src/trial-lifecycle.js");
  let now = 0;
  const events = [];
  const consentController = { canCollectResearch: true, registerCollector: () => () => true };
  const lifecycle = new TrialLifecycle({
    context: { experience_id: "exp-1", session_id: "session-1", study_id: "study-a" },
    timingRules: { version: "timing-v4", pause_on_hidden: false },
    onEvent: (event) => events.push(event), monotonicNow: () => now, wallClock: () => new Date("2026-01-02T03:04:05Z"),
    timers: { setTimeout: () => 1, clearTimeout() {} }, eventId: () => `event-${events.length + 1}`,
    consentController,
  });
  lifecycle.start("trial-2");
  now = 120;
  assert.equal(lifecycle.handleVisibility(true), false);
  assert.equal(lifecycle.state, "active");
  assert.equal(lifecycle.snapshot().elapsed_ms, 120);
  assert.equal(lifecycle.abort(), true);
  assert.equal(lifecycle.abort(), false);
  assert.equal(lifecycle.state, "aborted");
  assert.deepEqual(events.map((event) => event.event_type), ["trial.exposure_started", "trial.exposure_ended"]);
});

test("attached browser lifecycle pauses on hidden pages and aborts once on pagehide", async () => {
  const { TrialLifecycle } = await import("../src/trial-lifecycle.js");
  const doc = new FakeTarget();
  doc.visibilityState = "visible";
  const win = new FakeTarget();
  const events = [];
  const consentController = {
    canCollectResearch: true,
    registerCollector: () => () => true,
    registerListener(target, name, listener) { target.addEventListener(name, listener); return () => true; },
  };
  const lifecycle = new TrialLifecycle({
    context: { experience_id: "exp-1", session_id: "session-1", study_id: "study-a" },
    timingRules: { version: "timing-v5", pause_on_hidden: true },
    onEvent: (event) => events.push(event), monotonicNow: () => 10, wallClock: () => new Date("2026-01-02T03:04:05Z"),
    consentController,
  });
  const detach = lifecycle.attachLifecycle({ document: doc, window: win });
  lifecycle.start("trial-3");
  doc.visibilityState = "hidden";
  doc.fire("visibilitychange");
  assert.equal(lifecycle.state, "paused");
  win.fire("pagehide");
  win.fire("pagehide");
  assert.equal(lifecycle.state, "aborted");
  assert.deepEqual(events.map((event) => event.event_type), ["trial.exposure_started", "trial.exposure_ended"]);
  detach();
  assert.equal(doc.listeners.get("visibilitychange").size, 0);
  assert.equal(win.listeners.get("pagehide").size, 0);
});

test("withdrawal stops an active trial without emitting a post-withdrawal research event", async () => {
  const { TrialLifecycle } = await import("../src/trial-lifecycle.js");
  let canCollectResearch = true;
  let stopCollector;
  const events = [];
  const lifecycle = new TrialLifecycle({
    context: { experience_id: "exp-1", session_id: "session-1", study_id: "study-a" },
    timingRules: { version: "timing-v6", pause_on_hidden: true, duration_ms: 10000 },
    consentController: { get canCollectResearch() { return canCollectResearch; }, registerCollector(stop) { stopCollector = stop; return () => true; } },
    onEvent: (event) => events.push(event), monotonicNow: () => 20, wallClock: () => new Date("2026-01-02T03:04:05Z"),
    timers: { setTimeout: () => 1, clearTimeout() {} },
  });
  lifecycle.start("trial-withdrawal");
  canCollectResearch = false;
  stopCollector();
  assert.equal(lifecycle.state, "aborted");
  assert.equal(lifecycle.snapshot().elapsed_ms, 0);
  assert.deepEqual(events.map((event) => event.event_type), ["trial.exposure_started"]);
});

test("trial skip is terminal and cannot emit a second end event", async () => {
  const { TrialLifecycle } = await import("../src/trial-lifecycle.js");
  let now = 5;
  const events = [];
  const lifecycle = new TrialLifecycle({
    context: { experience_id: "exp-1", session_id: "session-1", study_id: "study-a" },
    timingRules: { version: "timing-v7", pause_on_hidden: false },
    consentController,
    onEvent: (event) => events.push(event), monotonicNow: () => now,
    wallClock: () => new Date("2026-01-02T03:04:05Z"), eventId: () => `event-${events.length + 1}`,
  });
  lifecycle.start("trial-skipped");
  now = 25;
  assert.equal(lifecycle.skip(), true);
  assert.equal(lifecycle.state, "skipped");
  assert.equal(lifecycle.snapshot().elapsed_ms, 20);
  assert.equal(lifecycle.complete(), false);
  assert.deepEqual(events.map((event) => event.event_type), ["trial.exposure_started", "trial.exposure_ended"]);
});
