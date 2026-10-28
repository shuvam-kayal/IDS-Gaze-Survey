import {
  fetchParticipantAoiConfigurations,
  fetchParticipantConfiguration,
  parseSessionBootstrap,
  parseStudyConfig,
  parseSurveyPlan,
} from "../../packages/participant-sdk/src/bootstrap.js";

function nonEmpty(value) {
  return typeof value === "string" && value.trim().length > 0;
}

function joinUrl(base, path) {
  return `${base.replace(/\/$/, "")}${path}`;
}

function timingRulesFor(details, studyId) {
  const entry = details.timing_rules.find((item) => item.study_id === studyId);
  const source = entry?.timing_rules ?? {};
  const duration = source.duration_ms ?? source.exposure_duration_ms;
  return {
    version: nonEmpty(source.version) ? source.version : `p2:${studyId}`,
    pause_on_hidden: source.pause_on_hidden !== false,
    allow_pause: source.allow_pause !== false,
    ...(Number.isFinite(duration) && duration > 0 ? { duration_ms: duration } : {}),
  };
}

function consentPolicy(bootstrap, gazeRequired) {
  const hostText = globalThis.IDS_LIVE_CONSENT_POLICY_TEXT;
  const researchText = nonEmpty(hostText?.research) ? hostText.research :
    `Participation is voluntary. You may stop at any time. Consent notice version: ${bootstrap.privacy_notice_version}.`;
  const cameraText = nonEmpty(hostText?.camera) ? hostText.camera :
    `Camera use is optional. You may continue without gaze data. Camera consent version: ${bootstrap.research_consent_version}.`;
  return {
    research: { version: bootstrap.research_consent_version, text: researchText },
    camera: { version: bootstrap.research_consent_version, offered: bootstrap.camera_capture_supported && gazeRequired, text: cameraText },
  };
}

/** Load the actual P2 participant resources; no fixture fallback is attempted. */
export async function loadLiveConfig({ apiBaseUrl, experienceId, fetchImpl = globalThis.fetch?.bind(globalThis), now = Date.now() } = {}) {
  if (!nonEmpty(apiBaseUrl) || !nonEmpty(experienceId)) {
    throw new TypeError("Live mode requires an API base URL and experience_id");
  }
  const base = apiBaseUrl.replace(/\/$/, "");
  const configuration = await fetchParticipantConfiguration({
    bootstrapUrl: joinUrl(base, "/v1/sessions/bootstrap"),
    experienceId,
    cameraCaptureSupported: Boolean(globalThis.navigator?.mediaDevices?.getUserMedia),
    studyConfigUrl: (studyId, version, sessionId) => joinUrl(base, `/v1/sessions/${encodeURIComponent(sessionId)}/studies/${encodeURIComponent(studyId)}/study-config?config_version=${encodeURIComponent(version)}`),
    questionConfigUrl: (studyId, version, sessionId) => joinUrl(base, `/v1/sessions/${encodeURIComponent(sessionId)}/studies/${encodeURIComponent(studyId)}/question-config?config_version=${encodeURIComponent(version)}`),
    surveyPlanUrl: (sessionId) => joinUrl(base, `/v1/sessions/${encodeURIComponent(sessionId)}/survey-plan`),
    surveyPlanDetailsUrl: (sessionId) => joinUrl(base, `/v1/sessions/${encodeURIComponent(sessionId)}/survey-plan-details`),
    fetchImpl,
    now,
  });
  const aoiConfigs = await fetchParticipantAoiConfigurations({
    bootstrap: configuration.bootstrap,
    aoiConfigUrl: (sessionId, studyId, version) => joinUrl(base, `/v1/sessions/${encodeURIComponent(sessionId)}/studies/${encodeURIComponent(studyId)}/aoi-config?config_version=${encodeURIComponent(version)}`),
    fetchImpl,
  });
  const study = configuration.bootstrap.eligible_studies[0];
  if (!study) throw new Error("The server assigned no eligible studies");
  const index = configuration.bootstrap.eligible_studies.findIndex((item) => item.study_id === study.study_id);
  const gazeStudyIds = configuration.studyConfigs.filter((item) => item.gaze_required).map((item) => item.study_id);
  return {
    mode: "live",
    api_base_url: base,
    event_ingestion_url: joinUrl(base, "/v1/events"),
    session_bootstrap: configuration.bootstrap,
    study_config: configuration.studyConfigs[index],
    study_configs: configuration.studyConfigs,
    question_config: configuration.questionConfigs[index],
    question_configs: configuration.questionConfigs,
    survey_plan: configuration.surveyPlan,
    survey_plan_details: configuration.surveyPlanDetails,
    trial_timing_rules: timingRulesFor(configuration.surveyPlanDetails, study.study_id),
    aoi_config: aoiConfigs[index],
    aoi_configs: aoiConfigs,
    gaze_study_ids: gazeStudyIds,
    consent_policy: consentPolicy(configuration.bootstrap, gazeStudyIds.length > 0),
  };
}

export async function loadOfflineConfig(fetchImpl = globalThis.fetch) {
  const response = await fetchImpl("./demo-config.json", { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error("Could not load the explicitly selected offline demo configuration");
  const value = await response.json();
  if (value.schema_version !== "1.0.0" || value.demo_mode !== true || typeof value.event_ingestion_url !== "string") {
    throw new Error("Unsupported offline demo configuration");
  }
  const bootstrap = parseSessionBootstrap(value.session_bootstrap);
  const study = parseStudyConfig(value.study_config, { bootstrap, study: bootstrap.eligible_studies[0] });
  const surveyPlan = parseSurveyPlan(value.survey_plan, { bootstrap });
  const studyConfigs = Array.isArray(value.study_configs) ? value.study_configs.map((item) => parseStudyConfig(item, { bootstrap })) : [study];
  const gazeStudyIds = studyConfigs.filter((item) => item.gaze_required).map((item) => item.study_id);
  return { ...value, mode: "offline", session_bootstrap: bootstrap, study_config: study, study_configs: studyConfigs, survey_plan: surveyPlan, gaze_study_ids: gazeStudyIds, consent_policy: consentPolicy(bootstrap, gazeStudyIds.length > 0) };
}

export function runtimeSelection(location = globalThis.location, globals = globalThis) {
  const params = new URL(location.href).searchParams;
  const mode = params.get("mode") || "live";
  if (mode !== "live" && mode !== "offline") throw new Error("mode must be live or offline");
  return {
    mode,
    apiBaseUrl: params.get("api_base_url") || globals.IDS_API_BASE_URL || "http://localhost:8000",
    experienceId: params.get("experience_id") || globals.IDS_EXPERIENCE_ID || "",
  };
}
