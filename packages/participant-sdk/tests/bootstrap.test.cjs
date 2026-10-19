const test = require("node:test");
const assert = require("node:assert/strict");

const now = Date.parse("2026-10-17T00:00:00Z");
const bootstrap = {
  schema_version: "1.0.0",
  session_id: "session-test-01",
  experience_id: "experience-test",
  participant_id: null,
  experience_config_version: "exp-v3",
  eligible_studies: [
    { study_id: "study-a", config_version: "study-v4", aoi_set_version: "aoi-v2", question_set_version: "questions-v3", priority: 1 },
    { study_id: "study-b", config_version: "study-v2", aoi_set_version: "aoi-v1", question_set_version: "questions-v1", priority: 2 },
  ],
  privacy_notice_version: "privacy-v2",
  research_consent_version: "consent-v5",
  camera_capture_supported: true,
  issued_at: "2026-10-16T00:00:00Z",
  expires_at: "2026-10-18T00:00:00Z",
};

test("parses a valid versioned bootstrap without replacing server-pinned IDs or versions", async () => {
  const { parseSessionBootstrap } = await import("../src/bootstrap.js");
  assert.deepEqual(parseSessionBootstrap(bootstrap, { now }), bootstrap);
  const { participant_id: _participantId, ...withoutParticipantId } = bootstrap;
  assert.equal(parseSessionBootstrap(withoutParticipantId, { now }).participant_id, undefined);
});

test("rejects unknown major and unsupported minor bootstrap versions", async () => {
  const { parseSessionBootstrap } = await import("../src/bootstrap.js");
  assert.throws(() => parseSessionBootstrap({ ...bootstrap, schema_version: "2.0.0" }, { now }), /Unsupported SessionBootstrap major version/);
  assert.throws(() => parseSessionBootstrap({ ...bootstrap, schema_version: "1.1.0" }, { now }), /Unsupported SessionBootstrap version/);
});

test("rejects invalid or expired bootstrap records and duplicate Study IDs", async () => {
  const { parseSessionBootstrap } = await import("../src/bootstrap.js");
  assert.throws(() => parseSessionBootstrap({ ...bootstrap, expires_at: "not-a-date" }, { now }), /UTC RFC 3339/);
  assert.throws(() => parseSessionBootstrap({ ...bootstrap, expires_at: "2026-02-31T00:00:00Z" }, { now }), /valid UTC RFC 3339/);
  assert.throws(() => parseSessionBootstrap({ ...bootstrap, expires_at: "2026-10-16T00:00:00Z" }, { now }), /expired|after issued_at/);
  assert.throws(() => parseSessionBootstrap({ ...bootstrap, eligible_studies: [bootstrap.eligible_studies[0], bootstrap.eligible_studies[0]] }, { now }), /duplicate Study ID/);
});

test("validates StudyConfig timing and the separate session-scoped SurveyPlan", async () => {
  const { parseSessionBootstrap, parseStudyConfig, parseSurveyPlan } = await import("../src/bootstrap.js");
  const parsed = parseSessionBootstrap(bootstrap, { now });
  const studyConfig = {
    schema_version: "1.0.0", study_id: "study-a", experience_id: "experience-test", config_version: "study-v4",
    status: "active", aoi_set_version: "aoi-v2", question_set_version: "questions-v3",
    survey_policy: { timing: "after_each_trial", consolidation: "deduplicate_by_question_id" }, gaze_required: false,
  };
  assert.equal(parseStudyConfig(studyConfig, { bootstrap: parsed, study: parsed.eligible_studies[0] }).survey_policy.timing, "after_each_trial");
  assert.throws(() => parseStudyConfig({ ...studyConfig, config_version: "stale-version" }, { bootstrap: parsed, study: parsed.eligible_studies[0] }), /does not match/);
  const surveyPlan = {
    schema_version: "1.0.0", survey_plan_id: "survey-plan-1", session_id: parsed.session_id,
    study_ids: ["study-a", "study-b"], question_ids: ["question-1"], presentation: "end_of_session",
  };
  assert.deepEqual(parseSurveyPlan(surveyPlan, { bootstrap: parsed }), surveyPlan);
  assert.throws(() => parseSurveyPlan({ ...surveyPlan, session_id: "wrong-session" }, { bootstrap: parsed }), /does not match/);
});

test("requests bootstrap without accepting or sending a browser origin value", async () => {
  const { fetchSessionBootstrap } = await import("../src/bootstrap.js");
  let request;
  const result = await fetchSessionBootstrap({
    endpoint: "https://api.example.test/v1/sessions/bootstrap",
    experienceId: bootstrap.experience_id,
    now,
    fetchImpl: async (_url, init) => {
      request = init;
      return { ok: true, json: async () => bootstrap };
    },
  });
  assert.equal(result.session_id, bootstrap.session_id);
  assert.deepEqual(JSON.parse(request.body), { experience_id: bootstrap.experience_id });
  assert.equal(Object.keys(request.headers).some((key) => key.toLowerCase() === "origin"), false);
});

test("loads version-pinned configs, separate survey plan, timing, and modality options", async () => {
  const { fetchParticipantConfiguration } = await import("../src/bootstrap.js");
  const configByStudy = new Map([
    ["study-a", {
      schema_version: "1.0.0", study_id: "study-a", experience_id: "experience-test", config_version: "study-v4",
      status: "active", aoi_set_version: "aoi-v2", question_set_version: "questions-v3",
      survey_policy: { timing: "after_each_trial", consolidation: "deduplicate_by_question_id" }, gaze_required: false,
    }],
    ["study-b", {
      schema_version: "1.0.0", study_id: "study-b", experience_id: "experience-test", config_version: "study-v2",
      status: "active", aoi_set_version: "aoi-v1", question_set_version: "questions-v1",
      survey_policy: { timing: "after_exposure", consolidation: "keep_study_scoped" }, gaze_required: false,
    }],
  ]);
  const surveyPlan = {
    schema_version: "1.0.0", survey_plan_id: "survey-plan-1", session_id: bootstrap.session_id,
    study_ids: ["study-a", "study-b"], question_ids: ["question-1"], presentation: "end_of_session",
  };
  const configuration = await fetchParticipantConfiguration({
    bootstrapUrl: "https://api.example.test/v1/sessions/bootstrap",
    experienceId: bootstrap.experience_id,
    studyConfigUrl: (studyId, version) => `https://api.example.test/v1/studies/${studyId}/configs/${version}`,
    surveyPlanUrl: (sessionId) => `https://api.example.test/v1/sessions/${sessionId}/survey-plan`,
    now,
    fetchImpl: async (url, init) => {
      if (init.method === "POST") return { ok: true, json: async () => bootstrap };
      if (url.includes("survey-plan")) return { ok: true, json: async () => surveyPlan };
      const studyId = url.includes("study-a") ? "study-a" : "study-b";
      return { ok: true, json: async () => configByStudy.get(studyId) };
    },
  });
  assert.deepEqual(configuration.studyConfigs.map(({ config_version }) => config_version), ["study-v4", "study-v2"]);
  assert.equal(configuration.studyConfigs[0].survey_policy.timing, "after_each_trial");
  assert.deepEqual(configuration.surveyPlan.study_ids, ["study-a", "study-b"]);
  assert.deepEqual(configuration.modalityOptions, { camera_capture_supported: true, gaze_required: false, non_gaze_available: true });
});

test("surfaces an origin authorization denial without trying an alternate path", async () => {
  const { fetchSessionBootstrap } = await import("../src/bootstrap.js");
  let calls = 0;
  await assert.rejects(fetchSessionBootstrap({
    endpoint: "https://api.example.test/v1/sessions/bootstrap",
    experienceId: bootstrap.experience_id,
    fetchImpl: async () => {
      calls += 1;
      return { ok: false, status: 403 };
    },
  }), /not authorized/);
  assert.equal(calls, 1);
});
