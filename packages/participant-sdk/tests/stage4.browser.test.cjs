const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const surveyModule = path.resolve(__dirname, "../src/survey.js");

test("accessible survey renders pinned question types and retries the same submission", async (t) => {
  let browser;
  try {
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_BIN || undefined, args: ["--no-sandbox"] });
    const page = await browser.newPage({ viewport: { width: 600, height: 800 } });
    await page.setContent("<!doctype html><html lang=\"en\"><body><main id=\"survey-root\"></main></body></html>");
    let source = fs.readFileSync(surveyModule, "utf8");
    source = source.replace("export function parseQuestionConfig", "function parseQuestionConfig")
      .replace("export function createSurveyRuntime", "function createSurveyRuntime")
      .replace("export function mountSurvey", "function mountSurvey")
      + "\nwindow.SurveySdk = { parseQuestionConfig, createSurveyRuntime, mountSurvey };";
    await page.addScriptTag({ content: source });
    await page.evaluate(() => {
      window.payloads = [];
      let attempt = 0;
      const config = {
        schema_version: "1.0.0", study_id: "study-1", question_set_version: "question-v3",
        questions: [
          { question_id: "single", prompt: "Pick one", answer_type: "single_choice", required: true, order: 0, options: [{ option_id: "a", label: "Option A" }, { option_id: "b", label: "Option B" }] },
          { question_id: "multi", prompt: "Pick multiple", answer_type: "multi_choice", required: true, order: 1, options: [{ option_id: "x", label: "Choice X" }, { option_id: "y", label: "Choice Y" }] },
          { question_id: "scale", prompt: "Rate this", answer_type: "scale", required: true, order: 2, options: [{ option_id: "low", label: "Low" }, { option_id: "high", label: "High" }] },
          { question_id: "boolean", prompt: "Would return?", answer_type: "boolean", required: true, order: 3 },
          { question_id: "text", prompt: "Optional comment", answer_type: "free_text", required: false, order: 4 },
        ],
      };
      const plan = { schema_version: "1.0.0", survey_plan_id: "plan-1", session_id: "session-1", study_ids: ["study-1"], question_ids: config.questions.map((question) => question.question_id), presentation: "end_of_session" };
      window.runtime = window.SurveySdk.createSurveyRuntime({
        questionConfigs: [config], surveyPlan: plan, context: { experience_id: "exp-1", session_id: "session-1" },
        consentController: { canCollectResearch: true, registerCollector: () => () => true },
        idFactory: (() => { let i = 0; return () => `id-${++i}`; })(),
        onSubmit: async (payload) => { window.payloads.push(payload); attempt += 1; if (attempt === 1) throw new Error("temporary"); return { accepted: true }; },
      });
      window.survey = window.SurveySdk.mountSurvey(document.querySelector("#survey-root"), {
        runtime: window.runtime,
        labels: { submit: "Submit answers", retry: "Retry submission", submitting: "Submitting…", retrying: "Retrying…", submitted: "Answers saved.", submitFailed: "Could not send answers.", requiredError: "Answer all required questions.", booleanTrue: "Yes", booleanFalse: "No" },
      });
    });

    await page.getByRole("radio", { name: "Option B" }).check();
    await page.getByRole("checkbox", { name: "Choice Y" }).check();
    await page.getByRole("checkbox", { name: "Choice X" }).check();
    await page.getByRole("radio", { name: "High" }).check();
    await page.getByRole("radio", { name: "Yes" }).check();
    await page.getByRole("textbox", { name: "Optional comment" }).fill("A comment response");
    await page.getByRole("button", { name: "Submit answers" }).click();
    await page.getByText("Could not send answers.").waitFor();
    assert.equal(await page.evaluate(() => window.runtime.state), "retryable");
    assert.equal(await page.getByRole("textbox", { name: "Optional comment" }).isDisabled(), true);
    await page.getByRole("button", { name: "Retry submission" }).click();
    await page.getByText("Answers saved.").waitFor();
    const payloads = await page.evaluate(() => window.payloads);
    assert.equal(payloads.length, 2);
    assert.deepEqual(payloads[0], payloads[1], "retry sends the identical payload and idempotency IDs");
    assert.deepEqual(payloads[0].responses.map((response) => response.question_id), ["single", "multi", "scale", "boolean", "text"]);
    assert.deepEqual(payloads[0].responses[1].answer, ["y", "x"], "multi-choice answer order follows participant selection order");
    assert.equal(payloads[0].responses[0].question_set_version, "question-v3");
  } catch (error) {
    if (/Executable doesn't exist|spawn .* ENOENT/.test(String(error))) {
      t.skip(`A local Chromium executable is required for this browser test: ${error.message}`);
      return;
    }
    throw error;
  } finally {
    if (browser) await browser.close();
  }
});
