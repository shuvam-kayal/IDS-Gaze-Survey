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
  const questionByStudy = new Map(bootstrap.eligible_studies.map((study) => [study.study_id, {
    schema_version: "1.0.0", study_id: study.study_id, question_set_version: study.question_set_version,
    questions: [{ question_id: `question-${study.study_id}`, prompt: "Question", answer_type: "free_text", required: false, order: 0 }],
  }]));
  const surveyPlanDetails = {
    schema_version: "1.0.0", survey_plan_id: surveyPlan.survey_plan_id,
    questions: [{ question_id: "question-1", question: questionByStudy.get("study-a").questions[0],
      origins: [{ study_id: "study-a", question_set_version: "questions-v3", question_version: "1", order: 0 }] }],
    question_origins: {}, timing_rules: [],
  };
  const configuration = await fetchParticipantConfiguration({
    bootstrapUrl: "https://api.example.test/v1/sessions/bootstrap",
    experienceId: bootstrap.experience_id,
    studyConfigUrl: (studyId, version) => `https://api.example.test/v1/studies/${studyId}/configs/${version}`,
    questionConfigUrl: (studyId, version) => `https://api.example.test/v1/studies/${studyId}/questions/${version}`,
    surveyPlanUrl: (sessionId) => `https://api.example.test/v1/sessions/${sessionId}/survey-plan`,
    surveyPlanDetailsUrl: (sessionId) => `https://api.example.test/v1/sessions/${sessionId}/survey-plan-details`,
    now,
    fetchImpl: async (url, init) => {
      if (init.method === "POST") return { ok: true, json: async () => bootstrap };
      if (url.includes("survey-plan-details")) return { ok: true, json: async () => surveyPlanDetails };
      if (url.includes("survey-plan")) return { ok: true, json: async () => surveyPlan };
      if (url.includes("/questions/")) {
        const studyId = url.includes("study-a") ? "study-a" : "study-b";
        return { ok: true, json: async () => questionByStudy.get(studyId) };
      }
      const studyId = url.includes("study-a") ? "study-a" : "study-b";
      return { ok: true, json: async () => configByStudy.get(studyId) };
    },
  });
  assert.deepEqual(configuration.studyConfigs.map(({ config_version }) => config_version), ["study-v4", "study-v2"]);
  assert.equal(configuration.studyConfigs[0].survey_policy.timing, "after_each_trial");
  assert.deepEqual(configuration.surveyPlan.study_ids, ["study-a", "study-b"]);
  assert.equal(configuration.questionConfigs.length, 2);
  assert.equal(configuration.surveyPlanDetails.survey_plan_id, surveyPlan.survey_plan_id);
  assert.deepEqual(configuration.modalityOptions, { camera_capture_supported: true, gaze_required: false, non_gaze_available: true });
});

test("survey runtime resolves consolidated aliases and identical questions from plan provenance", async () => {
  const { createSurveyRuntime } = await import("../src/survey.js");
  const configA = { schema_version: "1.0.0", study_id: "study-a", question_set_version: "qv-a", questions: [
    { question_id: "shared", prompt: "A", answer_type: "free_text", required: true, order: 0 },
  ] };
  const configB = { schema_version: "1.0.0", study_id: "study-b", question_set_version: "qv-b", questions: [
    { question_id: "shared", prompt: "B", answer_type: "free_text", required: true, order: 0 },
  ] };
  const surveyPlan = { schema_version: "1.0.0", survey_plan_id: "plan", session_id: "session-1",
    study_ids: ["study-a", "study-b"], question_ids: ["shared", "shared@alias"], presentation: "end_of_session" };
  const surveyPlanDetails = { schema_version: "1.0.0", survey_plan_id: "plan", questions: [
    { question_id: "shared", question: configA.questions[0], origins: [
      { study_id: "study-a", question_set_version: "qv-a", question_version: "1", order: 0 },
      { study_id: "study-b", question_set_version: "qv-b", question_version: "1", order: 0 },
    ] },
    { question_id: "shared@alias", question: configB.questions[0], origins: [
      { study_id: "study-b", question_set_version: "qv-b", question_version: "1", order: 0 },
    ] },
  ] };
  const runtime = createSurveyRuntime({ questionConfigs: [configA, configB], surveyPlan, surveyPlanDetails,
    context: { experience_id: "exp", session_id: "session-1" },
    consentController: { canCollectResearch: true, registerCollector: () => () => true },
    onSubmit: (payload) => payload });
  runtime.setAnswer("shared", "from A");
  runtime.setAnswer("shared@alias", "from B");
  const submitted = await runtime.submit();
  assert.deepEqual(submitted.responses.map((response) => [response.question_id, response.study_id, response.question_set_version]), [
    ["shared", "study-a", "qv-a"], ["shared@alias", "study-b", "qv-b"],
  ]);
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
