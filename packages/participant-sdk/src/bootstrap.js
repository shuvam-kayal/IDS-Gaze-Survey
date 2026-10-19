import { parseQuestionConfig } from "./survey.js";

const BOOTSTRAP_VERSION = "1.0.0";
const CONFIG_VERSION = "1.0.0";
const DATE_TIME_UTC = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$/;

function record(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function nonEmptyString(value) {
  return typeof value === "string" && value.trim().length > 0;
}

function utcDate(value, name) {
  if (typeof value !== "string" || !DATE_TIME_UTC.test(value) || !Number.isFinite(Date.parse(value))) {
    throw new TypeError(`${name} must be a UTC RFC 3339 timestamp`);
  }
  const timestamp = Date.parse(value);
  if (new Date(timestamp).toISOString().slice(0, 19) !== value.slice(0, 19)) {
    throw new TypeError(`${name} must be a valid UTC RFC 3339 timestamp`);
  }
  return timestamp;
}

function assertKeys(value, required, optional, name) {
  for (const key of required) {
    if (!Object.hasOwn(value, key)) throw new TypeError(`${name}.${key} is required`);
  }
  const allowed = new Set([...required, ...optional]);
  for (const key of Object.keys(value)) {
    if (!allowed.has(key)) throw new TypeError(`${name}.${key} is not allowed by its v1 contract`);
  }
}

/** Validate a server-provided SessionBootstrap v1 without filling in defaults. */
export function parseSessionBootstrap(value, { now = Date.now() } = {}) {
  if (!record(value)) throw new TypeError("SessionBootstrap must be an object");
  if (typeof value.schema_version !== "string") throw new TypeError("SessionBootstrap schema_version is required");
  const major = value.schema_version.split(".")[0];
  if (major !== "1") throw new TypeError(`Unsupported SessionBootstrap major version: ${major || "unknown"}`);
  if (value.schema_version !== BOOTSTRAP_VERSION) {
    throw new TypeError(`Unsupported SessionBootstrap version: ${value.schema_version}`);
  }

  const required = [
    "schema_version", "session_id", "experience_id", "experience_config_version",
    "eligible_studies", "privacy_notice_version", "research_consent_version",
    "camera_capture_supported", "issued_at", "expires_at",
  ];
  assertKeys(value, required, ["participant_id"], "SessionBootstrap");
  for (const key of ["session_id", "experience_id", "experience_config_version", "privacy_notice_version", "research_consent_version"]) {
    if (!nonEmptyString(value[key])) throw new TypeError(`SessionBootstrap.${key} must be a non-empty string`);
  }
  if (value.participant_id !== undefined && value.participant_id !== null && !nonEmptyString(value.participant_id)) {
    throw new TypeError("SessionBootstrap.participant_id must be a non-empty string or null");
  }
  if (typeof value.camera_capture_supported !== "boolean") {
    throw new TypeError("SessionBootstrap.camera_capture_supported must be a boolean");
  }
  const issuedAt = utcDate(value.issued_at, "SessionBootstrap.issued_at");
  const expiresAt = utcDate(value.expires_at, "SessionBootstrap.expires_at");
  if (expiresAt <= issuedAt) throw new TypeError("SessionBootstrap.expires_at must be after issued_at");
  if (expiresAt <= now) throw new TypeError("SessionBootstrap has expired");
  if (!Array.isArray(value.eligible_studies)) throw new TypeError("SessionBootstrap.eligible_studies must be an array");

  const ids = new Set();
  for (const [index, study] of value.eligible_studies.entries()) {
    const name = `SessionBootstrap.eligible_studies[${index}]`;
    if (!record(study)) throw new TypeError(`${name} must be an object`);
    for (const key of ["study_id", "config_version", "aoi_set_version", "question_set_version"]) {
      if (!Object.hasOwn(study, key) || !nonEmptyString(study[key])) throw new TypeError(`${name}.${key} must be a non-empty string`);
    }
    if (ids.has(study.study_id)) throw new TypeError(`duplicate Study ID: ${study.study_id}`);
    ids.add(study.study_id);
    if (study.priority !== undefined && !Number.isInteger(study.priority)) {
      throw new TypeError(`${name}.priority must be an integer`);
    }
  }
  return value;
}

/** Validate one immutable StudyConfig v1 pinned by SessionBootstrap. */
export function parseStudyConfig(value, { bootstrap, study } = {}) {
  if (!record(value)) throw new TypeError("StudyConfig must be an object");
  if (value.schema_version !== CONFIG_VERSION) throw new TypeError(`Unsupported StudyConfig version: ${value.schema_version}`);
  assertKeys(value,
    ["schema_version", "study_id", "experience_id", "config_version", "status", "aoi_set_version", "question_set_version", "survey_policy", "gaze_required"],
    ["priority"], "StudyConfig");
  for (const key of ["study_id", "experience_id", "config_version", "aoi_set_version", "question_set_version"]) {
    if (!nonEmptyString(value[key])) throw new TypeError(`StudyConfig.${key} must be a non-empty string`);
  }
  if (!["draft", "active", "paused", "closed"].includes(value.status)) throw new TypeError("StudyConfig.status is invalid");
  if (value.gaze_required !== false) throw new TypeError("StudyConfig.gaze_required must be false in v1");
  if (!record(value.survey_policy)) throw new TypeError("StudyConfig.survey_policy must be an object");
  assertKeys(value.survey_policy, ["timing", "consolidation"], [], "StudyConfig.survey_policy");
  if (!["before_exposure", "after_exposure", "after_each_trial", "batched_after_exposure"].includes(value.survey_policy.timing)) {
    throw new TypeError("StudyConfig.survey_policy.timing is invalid");
  }
  if (!["deduplicate_by_question_id", "keep_study_scoped"].includes(value.survey_policy.consolidation)) {
    throw new TypeError("StudyConfig.survey_policy.consolidation is invalid");
  }
  if (value.priority !== undefined && (!Number.isInteger(value.priority) || value.priority < 0)) {
    throw new TypeError("StudyConfig.priority must be a non-negative integer");
  }
  if (bootstrap && value.experience_id !== bootstrap.experience_id) throw new TypeError("StudyConfig Experience ID does not match SessionBootstrap");
  if (study && (value.study_id !== study.study_id || value.config_version !== study.config_version || value.aoi_set_version !== study.aoi_set_version || value.question_set_version !== study.question_set_version)) {
    throw new TypeError("StudyConfig does not match the version pinned by SessionBootstrap");
  }
  return value;
}

/** SurveyPlan is a separate frozen contract; it is not an extension of SessionBootstrap v1. */
export function parseSurveyPlan(value, { bootstrap } = {}) {
  if (!record(value)) throw new TypeError("SurveyPlan must be an object");
  if (value.schema_version !== CONFIG_VERSION) throw new TypeError(`Unsupported SurveyPlan version: ${value.schema_version}`);
  assertKeys(value, ["schema_version", "survey_plan_id", "session_id", "study_ids", "question_ids", "presentation"], [], "SurveyPlan");
  for (const key of ["survey_plan_id", "session_id"]) {
    if (!nonEmptyString(value[key])) throw new TypeError(`SurveyPlan.${key} must be a non-empty string`);
  }
  for (const key of ["study_ids", "question_ids"]) {
    if (!Array.isArray(value[key]) || value[key].some((id) => !nonEmptyString(id)) || new Set(value[key]).size !== value[key].length) {
      throw new TypeError(`SurveyPlan.${key} must contain unique non-empty strings`);
    }
  }
  if (value.study_ids.length === 0) throw new TypeError("SurveyPlan.study_ids must not be empty");
  if (value.presentation !== "end_of_session") throw new TypeError("SurveyPlan.presentation is invalid");
  if (bootstrap) {
    if (value.session_id !== bootstrap.session_id) throw new TypeError("SurveyPlan session does not match SessionBootstrap");
    const eligibleIds = new Set(bootstrap.eligible_studies.map(({ study_id }) => study_id));
    if (value.study_ids.some((id) => !eligibleIds.has(id))) throw new TypeError("SurveyPlan references a Study outside SessionBootstrap");
  }
  return value;
}

async function getJson(fetchImpl, url) {
  const response = await fetchImpl(url, { method: "GET", credentials: "omit", headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`Configuration request failed (${response.status})`);
  return response.json();
}

/**
 * Ask the server to authorize the browser Origin and issue a session bootstrap.
 * Never pass an Origin value: browsers set that protected header themselves.
 * The caller should invoke this only after the participant accepts the study.
 */
export async function fetchSessionBootstrap({ endpoint, experienceId, fetchImpl = globalThis.fetch, now = Date.now() }) {
  if (!nonEmptyString(endpoint) || !nonEmptyString(experienceId)) throw new TypeError("endpoint and experienceId are required");
  if (typeof fetchImpl !== "function") throw new TypeError("fetch is unavailable");
  const response = await fetchImpl(endpoint, {
    method: "POST",
    mode: "cors",
    credentials: "omit",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({ experience_id: experienceId }),
  });
  if (!response.ok) {
    if (response.status === 403) throw new Error("This website is not authorized for the configured Experience");
    throw new Error(`Session bootstrap request failed (${response.status})`);
  }
  const bootstrap = parseSessionBootstrap(await response.json(), { now });
  if (bootstrap.experience_id !== experienceId) throw new TypeError("Server returned a different Experience ID");
  return bootstrap;
}

/** Load pinned study configs and the separate consolidated survey plan. */
export async function fetchParticipantConfiguration({
  bootstrapUrl, experienceId, studyConfigUrl, questionConfigUrl, surveyPlanUrl, surveyPlanDetailsUrl,
  fetchImpl = globalThis.fetch, now = Date.now(),
}) {
  if (typeof studyConfigUrl !== "function" || typeof questionConfigUrl !== "function" ||
      typeof surveyPlanUrl !== "function" || typeof surveyPlanDetailsUrl !== "function") {
    throw new TypeError("study, question, survey plan, and survey plan details URL resolvers are required");
  }
  const bootstrap = await fetchSessionBootstrap({ endpoint: bootstrapUrl, experienceId, fetchImpl, now });
  const studyConfigs = await Promise.all(bootstrap.eligible_studies.map(async (study) => {
    const config = await getJson(fetchImpl, studyConfigUrl(study.study_id, study.config_version));
    return parseStudyConfig(config, { bootstrap, study });
  }));
  const questionConfigs = await Promise.all(bootstrap.eligible_studies.map(async (study) => {
    const raw = await getJson(fetchImpl, questionConfigUrl(study.study_id, study.question_set_version));
    const config = parseQuestionConfig(raw);
    if (config.study_id !== study.study_id || config.question_set_version !== study.question_set_version) {
      throw new TypeError("QuestionConfig identity/version does not match the SessionBootstrap pin");
    }
    return config;
  }));
  const surveyPlan = parseSurveyPlan(await getJson(fetchImpl, surveyPlanUrl(bootstrap.session_id)), { bootstrap });
  const surveyPlanDetails = await getJson(fetchImpl, surveyPlanDetailsUrl(bootstrap.session_id));
  if (!record(surveyPlanDetails) || surveyPlanDetails.schema_version !== "1.0.0" ||
      surveyPlanDetails.survey_plan_id !== surveyPlan.survey_plan_id || !Array.isArray(surveyPlanDetails.questions)) {
    throw new TypeError("SurveyPlan details are invalid or do not match the pinned plan");
  }
  const configsById = new Map(studyConfigs.map((config) => [config.study_id, config]));
  if (surveyPlan.study_ids.some((studyId) => !configsById.has(studyId))) {
    throw new TypeError("SurveyPlan references a Study with no pinned StudyConfig");
  }
  return {
    bootstrap,
    studyConfigs,
    questionConfigs,
    surveyPlan,
    surveyPlanDetails,
    modalityOptions: {
      camera_capture_supported: bootstrap.camera_capture_supported,
      gaze_required: studyConfigs.some((config) => config.gaze_required),
      non_gaze_available: true,
    },
  };
}
