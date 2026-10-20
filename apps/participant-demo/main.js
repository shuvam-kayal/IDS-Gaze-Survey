import { ConsentLifecycle } from "../../packages/participant-sdk/src/consent-lifecycle.js";
import { EventQueue } from "../../packages/participant-sdk/src/event-queue.js";
import { TrialLifecycle } from "../../packages/participant-sdk/src/trial-lifecycle.js";
import { createSurveyRuntime, mountSurvey } from "../../packages/participant-sdk/src/survey.js";
import { mountConsentFlow } from "../../packages/participant-sdk/src/consent-ui.js";
import { mountParticipantEntry } from "../../packages/participant-sdk/src/entry-widget.js";
import { startInteractionCapture } from "../../packages/participant-sdk/src/interactions.js";
import { createGeometryTracker } from "../../packages/participant-sdk/src/geometry.js";
import { loadLiveConfig, loadOfflineConfig, runtimeSelection } from "./runtime-config.js";

const $ = (selector) => document.querySelector(selector);
const experienceRoot = $("#experience");
const queueStatus = $("#queue-status");
let queue;
let detachQueueLifecycle = () => {};
let config;
let consent;
let trial;
let geometry;
let interaction;
let survey;
let trialActions;

function updateQueueStatus(result) {
  if (!queue) return;
  queueStatus.textContent = result
    ? `${result.delivered} event(s) delivered; ${result.remaining} waiting. ${result.error ? "The API is unavailable or rejected an event; it remains queued." : ""}`
    : `${queue.size} event(s) waiting in the bounded queue. The demo retries when the browser is online.`;
}
function enqueue(event) {
  if (!queue) return;
  try { queue.enqueue(event); updateQueueStatus(); void queue.flush().then(updateQueueStatus); }
  catch (error) { queueStatus.textContent = `${error.message} The event was not silently discarded.`; }
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
    const studyId = ctx.study_ids[0];
    trial = new TrialLifecycle({ context: { experience_id: ctx.experience_id, session_id: ctx.session_id, study_id: studyId }, timingRules: config.trial_timing_rules, consentController: consent, onEvent: enqueue, onState: (state) => {
      $("#trial-state").textContent = `Trial status: ${state.state}; elapsed ${Math.round(state.elapsed_ms)} ms.`;
      if (state.state === "completed" || state.state === "aborted" || state.state === "skipped") showSurvey();
    } });
    trial.attachLifecycle();
  }
  panel.innerHTML = `<h2>Study activity</h2><p>Read the sample content above, then start a short trial. The trial ends automatically after 15 seconds, or you can finish early.</p><p id="trial-state" role="status">Trial status: ready.</p><div class="actions"><button class="primary" id="start-trial">Start trial</button><button id="finish-trial" disabled>Finish trial</button></div><div id="trial-geometry" class="quiet"></div>`;
  $("#start-trial").addEventListener("click", () => {
    trial.start("demo-trial-1");
    $("#start-trial").disabled = true;
    $("#finish-trial").disabled = false;
  });
  $("#finish-trial").addEventListener("click", () => trial.complete());
}
function showSurvey() {
  if (survey || !consent?.canCollectResearch) return;
  const runtime = createSurveyRuntime({ questionConfigs: [config.question_config], surveyPlan: config.survey_plan, context: context(), consentController: consent, onSubmit: async (payload) => {
    // The API does not yet expose survey response persistence; this demo confirms locally.
    $("#survey-result").textContent = `Demo response ${payload.submission_id} saved in this page only.`;
    interaction?.stop(); geometry?.stop();
    const flushResult = await queue.close(); updateQueueStatus(flushResult);
    return { saved: true };
  } });
  survey = mountSurvey($("#survey"), { runtime, labels: { submit: "Submit sample answers", retrying: "Retrying…", retry: "Retry submission", requiredError: "Answer the required question before submitting.", booleanTrue: "Yes", booleanFalse: "No", success: "Thank you", retrySuccess: "Response submitted", retryFailure: "Submission failed; retry is available." } });
  const result = document.createElement("p"); result.id = "survey-result"; result.setAttribute("role", "status"); $("#survey").append(result);
}
function startJourney(modality) {
  experienceRoot.classList.remove("hidden");
  consent.registerCollector(() => { queue.purge(); detachQueueLifecycle(); updateQueueStatus(); });
  const ctx = context();
  enqueue(makeEnvelope("session.participation_started", { modality }));
  try {
    geometry = createGeometryTracker({ aoiConfig: config.aoi_config, context: { experience_id: ctx.experience_id, session_id: ctx.session_id, study_id: ctx.study_ids[0] }, controller: consent, onSnapshot: (snapshot) => { const target = $("#trial-geometry"); if (target) target.textContent = `AOI geometry updated (${snapshot.rectangles.length} visible area(s)).`; } });
    geometry.start();
  } catch (error) { console.warn("AOI tracking could not start in this browser:", error.message); }
  try {
    interaction = startInteractionCapture({ context: ctx, policy: { version: "demo-allowlist-1", allowed_event_types: ["interaction.click", "interaction.hover", "interaction.scroll", "page.visibility_changed"] }, controller: consent, onEvent: enqueue, allowedAoiIds: ["hero"], resolveAoiId: (target) => geometry?.resolveTarget(target) ?? null });
  } catch (error) { console.warn("Interaction capture could not start:", error.message); }
  showTrial();
}

async function startConsent() {
  if (!config) throw new Error("The participant configuration is not ready");
  experienceRoot.classList.remove("hidden");
  consent = new ConsentLifecycle({ policy: config.consent_policy,
    persistConsent: async (record) => { console.info("Demo consent choice recorded in memory:", record.scope, record.decision); },
    flushWithdrawalAudit: async () => ({ status: "sent" }),
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
    cameraOptions: { sessionId: config.session_bootstrap.session_id, provider, initialGeometry: { schema_version: "2.0.0", snapshot_id: "demo-initial-geometry", session_id: config.session_bootstrap.session_id, study_id: config.session_bootstrap.eligible_studies[0].study_id, captured_at: new Date().toISOString(), aoi_set_version: config.session_bootstrap.eligible_studies[0].aoi_set_version, viewport_width_px: innerWidth, viewport_height_px: innerHeight, scroll_x_px: scrollX, scroll_y_px: scrollY, zoom: visualViewport?.scale || 1, rectangles: [] }, onSample: () => {} },
    onContinue: ({ modality }) => startJourney(modality),
  });
}

const selection = runtimeSelection();
const loadConfig = selection.mode === "offline"
  ? () => loadOfflineConfig()
  : () => loadLiveConfig({ apiBaseUrl: selection.apiBaseUrl, experienceId: selection.experienceId });

void loadConfig().then((loaded) => {
  config = loaded;
  const modeNotice = document.createElement("p");
  modeNotice.className = "quiet";
  modeNotice.textContent = loaded.mode === "offline"
    ? "Offline demo mode: checked-in fixture only; no live P2 session is created."
    : `Live P2 mode: session configuration loaded for Experience ${loaded.session_bootstrap.experience_id}.`;
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
