import { ConsentLifecycle } from "../../packages/participant-sdk/src/consent-lifecycle.js";
import { EventQueue } from "../../packages/participant-sdk/src/event-queue.js";
import { TrialLifecycle } from "../../packages/participant-sdk/src/trial-lifecycle.js";
import { createSurveyRuntime, mountSurvey } from "../../packages/participant-sdk/src/survey.js";
import { mountConsentFlow } from "../../packages/participant-sdk/src/consent-ui.js";
import { mountParticipantEntry } from "../../packages/participant-sdk/src/entry-widget.js";
import { startInteractionCapture } from "../../packages/participant-sdk/src/interactions.js";
import { createGeometryTracker } from "../../packages/participant-sdk/src/geometry.js";
import { loadLiveConfig, loadOfflineConfig, runtimeSelection } from "./runtime-config.js";
import { recordParticipantConsent, submitParticipantSurvey, withdrawParticipantSession } from "../../packages/participant-sdk/src/bootstrap.js";

const $ = (selector) => document.querySelector(selector);
const experienceRoot = $("#experience");
const queueStatus = $("#queue-status");
const diagnostics = $("#diagnostics");
let queue;
let detachQueueLifecycle = () => {};
let config;
let consent;
let trial;
const trials = new Map();
let geometry;
const geometries = new Map();
let interaction;
let survey;
let trialActions;
let latestGeometry = null;
let trialGeometry = null;
const latestGeometries = new Map();
const trialGeometries = new Map();
let gazeSamples = [];
let gazeEnabled = false;
let trialStartAt = null;
let trialEndAt = null;
let trialResultSubmitted = false;
let trialSequence = 0;

function writeDiagnostics(message) {
  if (!diagnostics) return;
  const line = `[${new Date().toISOString()}] ${message}`;
  diagnostics.textContent = `${diagnostics.textContent === "Waiting for participant configuration…" ? "" : `${diagnostics.textContent}\n`}${line}`;
}

function newDemoTrialId() {
  trialSequence += 1;
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${trialSequence}`;
  return `demo-trial-${suffix}`;
}

function updateQueueStatus(result) {
  if (!queue) return;
  queueStatus.textContent = result
    ? `${result.delivered} event(s) delivered; ${result.remaining} waiting. ${result.error ? "The API is unavailable or rejected an event; it remains queued." : ""}`
    : `${queue.size} event(s) waiting in the bounded queue. The demo retries when the browser is online.`;
}
function enqueue(event) {
  if (!queue) return;
  if (event.event_type === "trial.exposure_started") trialStartAt = event.occurred_at;
  if (event.event_type === "trial.exposure_ended") trialEndAt = event.occurred_at;
  try { queue.enqueue(event); updateQueueStatus(); void queue.flush().then(updateQueueStatus); }
  catch (error) { queueStatus.textContent = `${error.message} The event was not silently discarded.`; }
}
function participantStateEndpoint() {
  return config.mode === "live" ? `${config.api_base_url}/v1` : null;
}
async function submitGazeTrial(trialId) {
  if (trialResultSubmitted || !gazeEnabled || config.mode !== "live") return;
  trialResultSubmitted = true;
  const target = $("#trial-geometry");
  try {
    await queue.flush();
    if (!trialStartAt || !trialEndAt) throw new Error("trial boundaries are unavailable");
    const samples = gazeSamples.filter((sample) => sample.occurred_at >= trialStartAt && sample.occurred_at < trialEndAt).slice(0, 250);
    writeDiagnostics(`Trial ${trialId}: ${samples.length} gaze sample(s) in the trusted trial window.`);
    const validSamples = samples.filter((sample) => sample.valid === true && Number.isFinite(sample.x_px) && Number.isFinite(sample.y_px));
    if (validSamples.length) {
      const xs = validSamples.map((sample) => sample.x_px); const ys = validSamples.map((sample) => sample.y_px);
      writeDiagnostics(`Trial ${trialId}: valid gaze bounds x=${Math.min(...xs)}..${Math.max(...xs)}, y=${Math.min(...ys)}..${Math.max(...ys)} (${validSamples.length} valid sample(s)); coordinates are viewport pixels.`);
    } else writeDiagnostics(`Trial ${trialId}: no valid viewport-coordinate samples were captured.`);
    if (!samples.length) throw new Error("no gaze samples in the completed trial window");
    const processed = [];
    for (const studyId of (config.gaze_study_ids ?? [])) {
      const observationGeometry = trialGeometries.get(studyId) || latestGeometries.get(studyId);
      if (!observationGeometry) throw new Error(`geometry is unavailable for Study ${studyId}`);
      const rectangleSummary = observationGeometry.rectangles.map((rectangle) => `${rectangle.aoi_id}[${rectangle.left_px},${rectangle.top_px}..${rectangle.right_px},${rectangle.bottom_px}]`).join("; ") || "none";
      writeDiagnostics(`Study ${studyId}: AOI version ${observationGeometry.aoi_set_version}; ${observationGeometry.rectangles.length} visible rectangle(s); viewport ${observationGeometry.viewport_width_px}x${observationGeometry.viewport_height_px}; ${rectangleSummary}.`);
      const geometryUrl = `${config.api_base_url}/v1/sessions/${encodeURIComponent(context().session_id)}/studies/${encodeURIComponent(studyId)}/trials/${encodeURIComponent(trialId)}/geometry`;
      const geometryResponse = await fetch(geometryUrl, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json", Accept: "application/json" }, body: JSON.stringify({ study_id: studyId, trial_id: trialId, snapshot: observationGeometry }) });
      if (!geometryResponse.ok) throw new Error(`geometry submission rejected for Study ${studyId} (${geometryResponse.status})`);
      writeDiagnostics(`Study ${studyId}: geometry accepted (${geometryResponse.status}).`);
      const response = await fetch(`${config.api_base_url}/v1/gaze/observations/authorized`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json", Accept: "application/json" }, body: JSON.stringify({ schema_version: "1.1.0", request_id: `gaze:${context().session_id}:${trialId}:${studyId}`, session_id: context().session_id, study_id: studyId, trial_id: trialId, provider_samples: samples }) });
      const body = await response.json();
      if (!response.ok) throw new Error(body?.detail || body?.error?.message || `gaze submission rejected for Study ${studyId} (${response.status})`);
      writeDiagnostics(`Study ${studyId}: authorized gaze response ${response.status}; P3 status ${body?.status ?? "not supplied"}.`);
      processed.push(`${studyId} (${body.status})`);
    }
    if (target) target.textContent = `Geometry accepted; gaze processed for ${processed.length} Study record(s) (${samples.length} sample(s)).`;
  } catch (error) {
    writeDiagnostics(`Gaze processing failed: ${error instanceof Error ? error.message : String(error)}`);
    if (target) target.textContent = `Gaze processing unavailable: ${error.message}`;
  }
}
function context() {
  const bootstrap = config.session_bootstrap;
  return { experience_id: bootstrap.experience_id, session_id: bootstrap.session_id, participant_id: bootstrap.participant_id, study_ids: bootstrap.eligible_studies.map((study) => study.study_id) };
}
function makeEnvelope(type, payload) {
  const ctx = context();
  return { schema_version: "1.0.0", event_id: crypto.randomUUID(), experience_id: ctx.experience_id, study_ids: ctx.study_ids, session_id: ctx.session_id, event_type: type, occurred_at: new Date().toISOString(), payload };
}
function showTrial() {
  const panel = $("#trial");
  if (!trial) {
    const ctx = context();
    const lifecycleStudyIds = config.gaze_study_ids?.length ? config.gaze_study_ids : [ctx.study_ids[0]];
    for (const studyId of lifecycleStudyIds) {
      const lifecycle = new TrialLifecycle({ context: { experience_id: ctx.experience_id, session_id: ctx.session_id, study_id: studyId }, timingRules: config.trial_timing_rules, consentController: consent, onEvent: enqueue, onState: (state) => {
        $("#trial-state").textContent = `Trial status: ${state.state}; elapsed ${Math.round(state.elapsed_ms)} ms.`;
      if (["completed", "aborted", "skipped"].includes(state.state)) {
        $("#start-trial").disabled = true;
        $("#finish-trial").disabled = true;
      }
      if (state.state === "completed" && lifecycle === trial) {
        // TrialLifecycle emits its completed state before emitting the terminal
        // exposure-ended event. Defer the server submission until the current
        // call stack finishes so the end event is queued and its flush can be
        // awaited before geometry/lifecycle validation runs.
        void Promise.resolve().then(() => submitGazeTrial(state.trial_id)).finally(() => showSurvey());
      }
      else if ((state.state === "aborted" || state.state === "skipped") && lifecycle === trial) showSurvey();
      } });
      trials.set(studyId, lifecycle);
      lifecycle.attachLifecycle();
    }
    trial = trials.get(lifecycleStudyIds[0]);
  }
  panel.innerHTML = `<h2>Study activity</h2><p>Read the sample content above, then start a short trial. The trial ends automatically after 15 seconds, or you can finish early.</p><p id="trial-state" role="status">Trial status: ready.</p><div class="actions"><button class="primary" id="start-trial">Start trial</button><button id="finish-trial" disabled>Finish trial</button></div><div id="trial-geometry" class="quiet"></div>`;
  $("#start-trial").addEventListener("click", () => {
    trialResultSubmitted = false;
    gazeSamples = [];
    trialStartAt = null;
    trialEndAt = null;
    trialGeometry = null;
    // Each run needs its own lifecycle identity. Reusing one trial ID after a
    // refresh or repeat leaves multiple valid start/end pairs in the same
    // session, which the server must reject as an ambiguous observation
    // window.
    const trialId = newDemoTrialId();
    trials.forEach((lifecycle) => lifecycle.start(trialId));
    trialGeometries.clear();
    geometries.forEach((tracker, studyId) => { const snapshot = tracker.flush({ force: true }) || latestGeometries.get(studyId); if (snapshot) trialGeometries.set(studyId, snapshot); });
    trialGeometry = trialGeometries.get((config.gaze_study_ids ?? [])[0]) || latestGeometry;
    latestGeometry = trialGeometry || latestGeometry;
    $("#start-trial").disabled = true;
    $("#finish-trial").disabled = false;
  });
  $("#finish-trial").addEventListener("click", () => {
    geometries.forEach((tracker, studyId) => { const snapshot = tracker.flush({ force: true }) || trialGeometries.get(studyId) || latestGeometries.get(studyId); if (snapshot) trialGeometries.set(studyId, snapshot); });
    trialGeometry = trialGeometries.get((config.gaze_study_ids ?? [])[0]) || trialGeometry || latestGeometry;
    trials.forEach((lifecycle) => lifecycle.complete());
  });
}
function showSurvey() {
  if (survey || !consent?.canCollectResearch) return;
  const runtime = createSurveyRuntime({ questionConfigs: config.question_configs ?? [config.question_config], surveyPlan: config.survey_plan, surveyPlanDetails: config.survey_plan_details, context: context(), consentController: consent, onSubmit: async (payload) => {
    try {
      if (config.mode === "live") await queue.flush();
      const result = config.mode === "live"
        ? await submitParticipantSurvey({ endpoint: participantStateEndpoint(), sessionId: context().session_id, submission: payload })
        : { duplicate: false, submission_id: payload.submission_id };
      if (config.mode === "live") {
        try { globalThis.sessionStorage?.setItem(`ids-participant-completed:${config.session_bootstrap.experience_id}`, "1"); } catch { /* storage may be unavailable */ }
      }
      $("#survey-result").textContent = config.mode === "live"
        ? `Response ${result.submission_id} persisted successfully${result.duplicate ? " (already received)" : ""}.`
        : `Offline demo response ${payload.submission_id} remains in this page only.`;
      interaction?.stop(); geometries.forEach((tracker) => tracker.stop()); geometry?.stop();
      await consent.stopCamera();
      const flushResult = await queue.close(); updateQueueStatus(flushResult);
      return result;
    } catch (error) {
      $("#survey-result").textContent = `Response was not persisted: ${error instanceof Error ? error.message : "the server rejected the submission"}`;
      throw error;
    }
  } });
  survey = mountSurvey($("#survey"), { runtime, labels: { submit: "Submit sample answers", retrying: "Retrying…", retry: "Retry submission", requiredError: "Answer the required question before submitting.", booleanTrue: "Yes", booleanFalse: "No", success: "Thank you", retrySuccess: "Response submitted", retryFailure: "Submission failed; retry is available." } });
  const result = document.createElement("p"); result.id = "survey-result"; result.setAttribute("role", "status"); $("#survey").append(result);
}
function startJourney(modality) {
  experienceRoot.classList.remove("hidden");
  gazeEnabled = modality === "gaze_and_non_gaze";
  consent.registerCollector(() => { queue.purge(); detachQueueLifecycle(); updateQueueStatus(); });
  const ctx = context();
  enqueue(makeEnvelope("session.participation_started", { modality }));
  const aoiConfigs = config.aoi_configs ?? [config.aoi_config];
  try {
    const gazeIds = new Set(config.gaze_study_ids ?? []);
    for (const aoiConfig of aoiConfigs) {
      if (!gazeIds.has(aoiConfig.study_id)) continue;
      const studyId = aoiConfig.study_id;
      const tracker = createGeometryTracker({ aoiConfig, context: { experience_id: ctx.experience_id, session_id: ctx.session_id, study_id: studyId }, controller: consent, onSnapshot: (snapshot) => { latestGeometries.set(studyId, snapshot); writeDiagnostics(`Study ${studyId}: AOI selector ${aoiConfig.aois.map((item) => item.selector).join(", ")}; ${snapshot.rectangles.length} visible rectangle(s).`); if (studyId === (config.gaze_study_ids ?? [])[0]) { latestGeometry = snapshot; const target = $("#trial-geometry"); if (target) target.textContent = `AOI geometry updated (${snapshot.rectangles.length} visible area(s)).`; } } });
      geometries.set(studyId, tracker); tracker.start();
    }
    geometry = geometries.get((config.gaze_study_ids ?? [])[0]) || null;
  } catch (error) { console.warn("AOI tracking could not start in this browser:", error.message); }
  try {
    const allAoiIds = [...new Set(aoiConfigs.flatMap((item) => (item.aois ?? []).map((aoi) => aoi.aoi_id)))];
    interaction = startInteractionCapture({ context: ctx, policy: { version: "demo-allowlist-1", allowed_event_types: ["interaction.click", "interaction.hover", "interaction.scroll", "page.visibility_changed"] }, controller: consent, onEvent: enqueue, allowedAoiIds: allAoiIds, resolveAoiId: (target) => { for (const tracker of geometries.values()) { const resolved = tracker.resolveTarget(target); if (resolved) return resolved; } return null; } });
  } catch (error) { console.warn("Interaction capture could not start:", error.message); }
  showTrial();
}

async function startConsent() {
  if (!config) throw new Error("The participant configuration is not ready");
  await globalThis.IDS_GAZE_PROVIDER_READY;
  experienceRoot.classList.remove("hidden");
  consent = new ConsentLifecycle({ policy: config.consent_policy,
    persistConsent: async (record) => {
      const endpoint = participantStateEndpoint();
      if (!endpoint) { console.info("Offline demo consent choice recorded in memory:", record.scope, record.decision); return; }
      await recordParticipantConsent({ endpoint, sessionId: config.session_bootstrap.session_id, record });
    },
    flushWithdrawalAudit: async () => {
      const endpoint = participantStateEndpoint();
      if (!endpoint) return { status: "sent" };
      await withdrawParticipantSession({ endpoint, sessionId: config.session_bootstrap.session_id, occurredAt: new Date().toISOString() });
      return { status: "sent" };
    },
  });
  const externalProvider = window.IDS_GAZE_PROVIDER;
  const provider = externalProvider ?? {
    async start({ on_status }) { on_status("unavailable", "No P3 provider adapter is installed in this demo."); },
    async stop() {},
  };
  mountConsentFlow($("#consent"), {
    controller: consent,
    policy: config.consent_policy,
    labels: {
      researchTitle: "Research participation", acceptResearch: "I agree to participate", declineResearch: "Decline", cameraTitle: "Optional camera and gaze tracking",
      cameraReadyToStart: "You can continue without camera access, or request camera access after agreeing separately.", startCamera: "Request camera and start provider", cameraStarting: "Checking camera and provider…", cameraActive: "Camera and gaze provider are active.",
      cameraDenied: "Camera permission was denied. You can continue without gaze.", cameraUnavailable: "No usable camera is available. You can continue without gaze.", cameraUnsupported: "This browser does not support camera access. You can continue without gaze.", cameraInterrupted: "Camera capture stopped. You can retry or continue without gaze.", cameraUnplugged: "The camera was disconnected. You can retry or continue without gaze.", cameraRevoked: "Camera permission was revoked. You can continue without gaze.", providerFailed: "The gaze provider could not start. The survey remains available without gaze.", retryCamera: "Try camera again", continueWithoutGaze: "Continue without gaze", acceptCamera: "I agree to optional camera use", declineCamera: "Continue without camera",
      declinedTitle: "You declined", declinedDescription: "No participation session or research events were created.", completeTitle: "Ready for the study", completeWithCameraDescription: "Your optional camera path is active.", completeWithoutCameraDescription: "You can continue with the study without gaze data.", withdrawnDescription: "Your participation has stopped.", withdraw: "Withdraw from study", withdrawing: "Stopping collection…", withdrawn: "Participation stopped.", withdrawnAuditUnavailable: "Participation stopped; the audit signal could not be sent.", retryWithdrawalAudit: "Retry stop signal", saving: "Saving your choice…", saveFailed: "Your choice could not be saved. Please try again.",
    },
    cameraOptions: { sessionId: config.session_bootstrap.session_id, provider, initialGeometry: (() => { const study = config.session_bootstrap.eligible_studies.find((item) => (config.gaze_study_ids ?? []).includes(item.study_id)) ?? config.session_bootstrap.eligible_studies[0]; return { schema_version: "2.0.0", snapshot_id: "demo-initial-geometry", session_id: config.session_bootstrap.session_id, study_id: study.study_id, captured_at: new Date().toISOString(), aoi_set_version: study.aoi_set_version, viewport_width_px: innerWidth, viewport_height_px: innerHeight, scroll_x_px: scrollX, scroll_y_px: scrollY, zoom: visualViewport?.scale || 1, rectangles: [] }; })(), onSample: (sample) => { if (gazeSamples.length < 250) gazeSamples.push(sample); } },
    onContinue: ({ modality }) => startJourney(modality),
  });
}

const selection = runtimeSelection();
const loadConfig = selection.mode === "offline"
  ? () => loadOfflineConfig()
  : () => {
    let newSession = false;
    try { newSession = globalThis.sessionStorage?.getItem(`ids-participant-completed:${selection.experienceId}`) === "1"; } catch { /* storage may be unavailable */ }
    return loadLiveConfig({ apiBaseUrl: selection.apiBaseUrl, experienceId: selection.experienceId, newSession });
  };

void loadConfig().then((loaded) => {
  config = loaded;
  writeDiagnostics(`Session ${loaded.session_bootstrap.session_id}; Experience ${loaded.session_bootstrap.experience_id}; assigned Studies ${loaded.session_bootstrap.eligible_studies.map((study) => study.study_id).join(", ") || "none"}.`);
  writeDiagnostics(`Gaze-enabled Studies: ${(loaded.gaze_study_ids ?? []).join(", ") || "none"}.`);
  const modeNotice = document.createElement("p");
  modeNotice.className = "quiet";
  modeNotice.textContent = loaded.mode === "offline"
    ? "Offline demo mode: checked-in fixture only; no live P2 session is created."
    : `Live P2 mode: session ${loaded.session_bootstrap.session_id} loaded for Experience ${loaded.session_bootstrap.experience_id}.`;
  $("#journey").prepend(modeNotice);
  queue = new EventQueue({ endpoint: config.event_ingestion_url, maxQueueSize: 500 });
  detachQueueLifecycle = queue.attachLifecycle({ window });
  mountParticipantEntry($("#entry"), {
    experienceId: config.session_bootstrap.experience_id,
    invitation: { title: "Take part in a short research study?", description: "Participation is voluntary. You can decline, and camera use is a separate optional choice.", buttonLabel: "View study invitation", acceptLabel: "Continue", declineLabel: "Decline", declinedTitle: "No problem", declinedDescription: "You have not joined the study. No session was started.", closeLabel: "Close", startingLabel: "Loading the consent information…", errorMessage: "The consent information could not be loaded. Please try again." },
    onAccept: startConsent,
  });
}).catch((error) => {
  $("#entry").textContent = `Participant configuration could not be loaded: ${error.message}`;
  console.error(error);
});
