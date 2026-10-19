function object(value) { return value !== null && typeof value === "object" && !Array.isArray(value); }
function nonEmpty(value) { return typeof value === "string" && value.trim().length > 0; }
function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (object(value)) return Object.fromEntries(Object.keys(value).sort().map((key) => [key, stable(value[key])]));
  return value;
}
function assertKeys(value, required, optional, name) {
  for (const key of required) if (!(key in value)) throw new TypeError(`${name}.${key} is required`);
  const allowed = new Set([...required, ...optional]);
  for (const key of Object.keys(value)) if (!allowed.has(key)) throw new TypeError(`${name}.${key} is not supported`);
}

export function parseQuestionConfig(value) {
  if (!object(value)) throw new TypeError("QuestionConfig must be an object");
  assertKeys(value, ["schema_version", "study_id", "question_set_version", "questions"], [], "QuestionConfig");
  if (value.schema_version !== "1.0.0") throw new TypeError("Unsupported QuestionConfig schema version");
  if (!nonEmpty(value.study_id) || !nonEmpty(value.question_set_version) || !Array.isArray(value.questions)) {
    throw new TypeError("QuestionConfig study, version, and questions are required");
  }
  const ids = new Set();
  const questions = value.questions.map((question, index) => {
    if (!object(question)) throw new TypeError(`QuestionConfig.questions[${index}] must be an object`);
    assertKeys(question, ["question_id", "prompt", "answer_type", "required", "order"], ["options"], `Question ${index}`);
    if (!nonEmpty(question.question_id) || !nonEmpty(question.prompt)) throw new TypeError(`Question ${index} requires an ID and prompt`);
    if (ids.has(question.question_id)) throw new TypeError(`Duplicate question ID ${question.question_id}`);
    ids.add(question.question_id);
    if (!["single_choice", "multi_choice", "free_text", "scale", "boolean"].includes(question.answer_type)) throw new TypeError(`Unsupported answer type for ${question.question_id}`);
    if (typeof question.required !== "boolean" || !Number.isInteger(question.order) || question.order < 0) throw new TypeError(`Question ${question.question_id} has invalid required/order values`);
    let options;
    if (question.options !== undefined) {
      if (!Array.isArray(question.options)) throw new TypeError(`Question ${question.question_id}.options must be an array`);
      const optionIds = new Set();
      options = question.options.map((option, optionIndex) => {
        if (!object(option)) throw new TypeError(`Question ${question.question_id} option ${optionIndex} must be an object`);
        if (!("option_id" in option) || !("label" in option)) throw new TypeError(`Question ${question.question_id} option ${optionIndex} requires option_id and label`);
        if (!nonEmpty(option.option_id) || !nonEmpty(option.label) || optionIds.has(option.option_id)) throw new TypeError(`Question ${question.question_id} has an invalid or duplicate option`);
        optionIds.add(option.option_id);
        return { option_id: option.option_id, label: option.label };
      });
    }
    if (["single_choice", "multi_choice", "scale"].includes(question.answer_type) && (!options || options.length === 0)) {
      throw new TypeError(`Question ${question.question_id} needs versioned options to enforce answer constraints`);
    }
    if (question.answer_type === "boolean" && options && (options.length !== 2 || !options.some((option) => option.option_id === "true") || !options.some((option) => option.option_id === "false"))) {
      throw new TypeError(`Boolean question ${question.question_id} options must use true and false IDs`);
    }
    if (question.answer_type === "free_text" && options) throw new TypeError(`Free-text question ${question.question_id} cannot define choices`);
    return { ...question, ...(options ? { options } : {}) };
  });
  return { schema_version: value.schema_version, study_id: value.study_id, question_set_version: value.question_set_version, questions };
}

function makeId() { return globalThis.crypto?.randomUUID?.() || `resp-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`; }
function empty(answer) { return answer === undefined || answer === null || answer === "" || (Array.isArray(answer) && answer.length === 0); }

export function createSurveyRuntime({ questionConfigs, surveyPlan, surveyPlanDetails, context, consentController, onSubmit, idFactory = makeId } = {}) {
  if (!Array.isArray(questionConfigs) || questionConfigs.length === 0) throw new TypeError("At least one versioned QuestionConfig is required");
  if (!object(surveyPlan) || surveyPlan.schema_version !== "1.0.0" || surveyPlan.presentation !== "end_of_session" || !Array.isArray(surveyPlan.question_ids)) {
    throw new TypeError("A valid versioned ConsolidatedSurveyPlan is required");
  }
  assertKeys(surveyPlan, ["schema_version", "survey_plan_id", "session_id", "study_ids", "question_ids", "presentation"], [], "SurveyPlan");
  if (!context || !nonEmpty(context.session_id) || !nonEmpty(context.experience_id)) throw new TypeError("session_id and experience_id are required");
  if (surveyPlan.session_id !== context.session_id || !nonEmpty(surveyPlan.survey_plan_id) || !Array.isArray(surveyPlan.study_ids) || !surveyPlan.study_ids.length) {
    throw new TypeError("SurveyPlan must be versioned for this session and contain study IDs");
  }
  if (context.participant_id !== undefined && context.participant_id !== null && !nonEmpty(context.participant_id)) throw new TypeError("participant_id must be a non-empty string or null");
  if (!consentController || typeof consentController.registerCollector !== "function") throw new TypeError("ConsentLifecycle controller is required");
  if (typeof onSubmit !== "function" || typeof idFactory !== "function") throw new TypeError("onSubmit and idFactory functions are required");
  const configs = questionConfigs.map(parseQuestionConfig);
  if (new Set(surveyPlan.study_ids).size !== surveyPlan.study_ids.length || surveyPlan.study_ids.some((id) => !nonEmpty(id))) throw new TypeError("SurveyPlan study IDs must be unique non-empty strings");
  const eligibleStudyIds = new Set(surveyPlan.study_ids);
  const questionsById = new Map();
  for (const config of configs) {
    if (eligibleStudyIds.size && !eligibleStudyIds.has(config.study_id)) continue;
    for (const question of config.questions) {
      const refs = questionsById.get(question.question_id) || [];
      refs.push({ question, study_id: config.study_id, question_set_version: config.question_set_version });
      questionsById.set(question.question_id, refs);
    }
  }
  if (!Array.isArray(surveyPlan.question_ids) || surveyPlan.question_ids.length === 0) throw new TypeError("SurveyPlan requires question IDs");
  if (new Set(surveyPlan.question_ids).size !== surveyPlan.question_ids.length) throw new TypeError("SurveyPlan question IDs must be unique");
  let orderedQuestions;
  if (surveyPlanDetails !== undefined) {
    if (!object(surveyPlanDetails) || surveyPlanDetails.schema_version !== "1.0.0" ||
        surveyPlanDetails.survey_plan_id !== surveyPlan.survey_plan_id || !Array.isArray(surveyPlanDetails.questions)) {
      throw new TypeError("SurveyPlan details must match the pinned plan");
    }
    const detailsById = new Map(surveyPlanDetails.questions.map((item) => [item.question_id, item]));
    orderedQuestions = surveyPlan.question_ids.map((id) => {
      const detail = detailsById.get(id);
      if (!detail || !object(detail.question) || !Array.isArray(detail.origins) || detail.origins.length === 0) {
        throw new TypeError(`SurveyPlan question ${id} has no valid provenance details`);
      }
      const origin = detail.origins[0];
      const config = configs.find((candidate) => candidate.study_id === origin.study_id && candidate.question_set_version === origin.question_set_version);
      const source = config?.questions.find((question) => question.question_id === detail.question.question_id);
      if (!source || JSON.stringify(stable(source)) !== JSON.stringify(stable(detail.question))) {
        throw new TypeError(`SurveyPlan question ${id} does not match its pinned source config`);
      }
      return { question: { ...source, question_id: id }, study_id: origin.study_id, question_set_version: origin.question_set_version };
    });
  } else {
    orderedQuestions = surveyPlan.question_ids.map((id) => {
      const refs = questionsById.get(id) || [];
      if (refs.length !== 1) throw new TypeError(`SurveyPlan question ${id} must resolve to exactly one pinned question config`);
      return refs[0];
    });
  }
  const answerValues = new Map();
  let state = "editing";
  let frozenPayload = null;
  let inflight = null;
  let completedResult;
  let abortController = null;

  function setAnswer(questionId, answer) {
    if (!consentController.canCollectResearch) throw new Error("Research collection is not active");
    if (state !== "editing") throw new Error("Survey answers are locked after submission starts; retry the same submission");
    const ref = orderedQuestions.find((entry) => entry.question.question_id === questionId);
    if (!ref) throw new TypeError(`Unknown survey question ${questionId}`);
    const question = ref.question;
    if (empty(answer)) {
      answerValues.delete(questionId);
      return;
    }
    if (question.answer_type === "single_choice" || question.answer_type === "scale") {
      if (typeof answer !== "string" || !question.options.some((option) => option.option_id === answer)) throw new TypeError(`Answer for ${questionId} must match a configured option`);
    } else if (question.answer_type === "multi_choice") {
      if (!Array.isArray(answer) || answer.some((id) => typeof id !== "string" || !question.options.some((option) => option.option_id === id)) || new Set(answer).size !== answer.length) {
        throw new TypeError(`Answer for ${questionId} must contain unique configured option IDs`);
      }
    } else if (question.answer_type === "boolean") {
      if (typeof answer !== "boolean") throw new TypeError(`Answer for ${questionId} must be boolean`);
    } else if (question.answer_type === "free_text") {
      if (typeof answer !== "string") throw new TypeError(`Answer for ${questionId} must be text`);
    }
    answerValues.set(questionId, Array.isArray(answer) ? [...answer] : answer);
  }

  function validate() {
    const missing = orderedQuestions.filter(({ question }) => question.required && empty(answerValues.get(question.question_id))).map(({ question }) => question.question_id);
    if (missing.length) throw Object.assign(new Error("Complete the required questions before submitting"), { missing_question_ids: missing });
  }

  function buildPayload() {
    const submissionId = idFactory();
    const responses = orderedQuestions.flatMap(({ question, study_id, question_set_version }) => {
      const answer = answerValues.get(question.question_id);
      if (empty(answer)) return [];
      return [{
        response_id: idFactory(), submission_id: submissionId,
        experience_id: context.experience_id, session_id: context.session_id,
        ...(context.participant_id !== undefined ? { participant_id: context.participant_id } : {}),
        study_id, question_id: question.question_id, question_set_version,
        answer_type: question.answer_type, answer: Array.isArray(answer) ? [...answer] : answer,
      }];
    });
    return Object.freeze({
      submission_id: submissionId,
      session_id: context.session_id,
      responses: Object.freeze(responses.map((response) => Object.freeze({
        ...response,
        answer: Array.isArray(response.answer) ? Object.freeze([...response.answer]) : response.answer,
      }))),
    });
  }

  async function submit() {
    if (state === "complete") return completedResult;
    if (state === "stopped" || !consentController.canCollectResearch) throw new Error("Research collection is not active");
    if (inflight) return inflight;
    if (!frozenPayload) {
      validate();
      frozenPayload = buildPayload();
    }
    state = "submitting";
    abortController = new AbortController();
    const activeAbortController = abortController;
    const activePayload = frozenPayload;
    const unregisterSubmission = consentController.registerCollector(() => {
      activeAbortController.abort();
      stop();
    });
    inflight = Promise.resolve().then(() => {
      if (state === "stopped" || !consentController.canCollectResearch || activeAbortController.signal.aborted) throw new Error("Survey submission stopped before collection");
      return onSubmit(activePayload, { signal: activeAbortController.signal });
    }).then((result) => {
      if (state === "stopped") throw new Error("Survey submission ended with consent withdrawal");
      completedResult = result;
      state = "complete";
      return result;
    }).catch((error) => {
      if (state !== "stopped") state = "retryable";
      throw error;
    }).finally(() => { inflight = null; abortController = null; unregisterSubmission(); });
    return inflight;
  }

  function stop() {
    if (state === "stopped") return;
    state = "stopped";
    answerValues.clear();
    frozenPayload = null;
    abortController?.abort();
  }

  function registerCollector(callback) { return consentController.registerCollector(callback); }

  return {
    questions: orderedQuestions.map((entry) => ({ ...entry.question, study_id: entry.study_id, question_set_version: entry.question_set_version })),
    get canCollectResearch() { return consentController.canCollectResearch === true; },
    get state() { return state; },
    get submissionId() { return frozenPayload?.submission_id ?? null; },
    getPayloadForRetry() { return frozenPayload; },
    registerCollector,
    setAnswer,
    getAnswer: (id) => answerValues.get(id),
    submit,
    stop,
  };
}

function el(doc, tag, text, attributes = {}) {
  const node = doc.createElement(tag);
  if (text !== undefined) node.textContent = text;
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  return node;
}

/** Accessible survey renderer. Question copy/options come only from pinned P2 config. */
export function mountSurvey(root, { runtime, labels, document: doc = globalThis.document } = {}) {
  if (!root?.replaceChildren || !runtime || typeof runtime.setAnswer !== "function" || typeof runtime.submit !== "function") throw new TypeError("Survey root and runtime are required");
  if (!labels || !doc?.createElement) throw new TypeError("Survey labels and browser document are required");
  if (!runtime.canCollectResearch) throw new Error("Research consent is required before rendering a study survey");
  const form = el(doc, "form", undefined, { novalidate: "" });
  const status = el(doc, "p", "", { role: "status", "aria-live": "polite" });
  const errors = el(doc, "div", undefined, { role: "alert" });
  const controlsById = new Map();
  const selectedOptionOrder = new Map();
  for (const question of runtime.questions) {
    const group = el(doc, "fieldset");
    group.append(el(doc, "legend", question.prompt));
    const controls = [];
    const makeOption = (inputType, value, label, name) => {
      const wrapper = el(doc, "label");
      const input = el(doc, "input", undefined, { type: inputType, name, value });
      if (question.required && inputType !== "checkbox") input.required = true;
      wrapper.append(input, doc.createTextNode(label));
      group.append(wrapper);
      controls.push(input);
    };
    const name = `survey-${question.question_id}`;
    if (question.answer_type === "single_choice" || question.answer_type === "scale") {
      for (const option of question.options) makeOption("radio", option.option_id, option.label, name);
    } else if (question.answer_type === "multi_choice") {
      const selected = [];
      selectedOptionOrder.set(question.question_id, selected);
      for (const option of question.options) {
        makeOption("checkbox", option.option_id, option.label, name);
        const input = controls.at(-1);
        input.addEventListener("change", () => {
          const existing = selected.indexOf(input.value);
          if (input.checked && existing < 0) selected.push(input.value);
          else if (!input.checked && existing >= 0) selected.splice(existing, 1);
        });
      }
    } else if (question.answer_type === "boolean") {
      const boolOptions = question.options || [{ option_id: "true", label: labels.booleanTrue }, { option_id: "false", label: labels.booleanFalse }];
      for (const option of boolOptions) makeOption("radio", option.option_id, option.label, name);
    } else if (question.answer_type === "free_text") {
      const input = el(doc, "textarea", undefined, { name, "aria-label": question.prompt });
      input.required = question.required;
      group.append(input);
      controls.push(input);
    }
    controlsById.set(question.question_id, controls);
    form.append(group);
  }
  const submitButton = el(doc, "button", labels.submit, { type: "submit" });
  form.append(errors, status, submitButton);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errors.textContent = "";
    if (runtime.state === "retryable") {
      submitButton.disabled = true;
      status.textContent = labels.retrying;
    } else {
      for (const question of runtime.questions) {
        const controls = controlsById.get(question.question_id) || [];
        if (question.answer_type === "multi_choice") {
          runtime.setAnswer(question.question_id, selectedOptionOrder.get(question.question_id).filter((id) => controls.some((control) => control.checked && control.value === id)));
        } else if (question.answer_type === "single_choice" || question.answer_type === "scale") {
          const selected = controls.find((control) => control.checked);
          runtime.setAnswer(question.question_id, selected?.value ?? null);
        } else if (question.answer_type === "boolean") {
          const selected = controls.find((control) => control.checked);
          runtime.setAnswer(question.question_id, selected ? selected.value === "true" : null);
        } else {
          runtime.setAnswer(question.question_id, controls[0]?.value ?? "");
        }
      }
      submitButton.disabled = true;
      status.textContent = labels.submitting;
    }
    try {
      await runtime.submit();
      status.textContent = labels.submitted;
      form.querySelectorAll("input,textarea,button").forEach((control) => { control.disabled = true; });
    } catch (error) {
      submitButton.disabled = false;
      status.textContent = labels.submitFailed;
      if (error.missing_question_ids) errors.textContent = labels.requiredError;
      else if (runtime.state === "retryable") {
        form.querySelectorAll("input,textarea").forEach((control) => { control.disabled = true; });
        submitButton.textContent = labels.retry;
      }
    }
  });
  root.replaceChildren(form);
  const unregisterSurvey = runtime.registerCollector(() => {
    runtime.stop();
    form.querySelectorAll("input,textarea,button").forEach((control) => { control.disabled = true; });
    root.replaceChildren();
  });
  return { form, runtime, destroy() { unregisterSurvey(); runtime.stop(); root.replaceChildren(); } };
}
