const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const lifecycleModule = path.resolve(__dirname, "../src/consent-lifecycle.js");
const uiModule = path.resolve(__dirname, "../src/consent-ui.js");

test("browser presents separate research and camera choices and records both before completion", async (t) => {
  let browser;
  try {
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_BIN || undefined, args: ["--no-sandbox"] });
    const page = await browser.newPage({ viewport: { width: 390, height: 760 } });
    await page.setContent("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"></head><body><main id=\"consent-root\"></main></body></html>");
    const lifecycleSource = fs.readFileSync(lifecycleModule, "utf8")
      .replace("export class ConsentLifecycle", "class ConsentLifecycle")
      + "\nwindow.ConsentLifecycle = ConsentLifecycle;";
    const uiSource = fs.readFileSync(uiModule, "utf8")
      .replace("export function mountConsentFlow", "function mountConsentFlow")
      + "\nwindow.mountConsentFlow = mountConsentFlow;";
    await page.addScriptTag({ content: lifecycleSource });
    await page.addScriptTag({ content: uiSource });
    await page.evaluate(() => {
      window.consentRecords = [];
      window.auditSignals = 0;
      window.controller = new window.ConsentLifecycle({
        policy: {
          research: { version: "research-policy-v7", text: "Taking part in this research is optional." },
          camera: { version: "camera-policy-v4", text: "Camera gaze tracking is a separate optional choice.", offered: true },
        },
        persistConsent: async (record) => window.consentRecords.push(record),
        flushWithdrawalAudit: async () => { window.auditSignals += 1; },
      });
      window.flow = window.mountConsentFlow(document.querySelector("#consent-root"), {
        controller: window.controller,
        policy: {
          research: { version: "research-policy-v7", text: "Taking part in this research is optional." },
          camera: { version: "camera-policy-v4", text: "Camera gaze tracking is a separate optional choice.", offered: true },
        },
        onContinue: (result) => { window.continuedWith = result; },
        labels: {
          researchTitle: "Research participation consent", acceptResearch: "Agree to research", declineResearch: "Decline research",
          cameraTitle: "Camera and gaze consent", acceptCamera: "Agree to camera", declineCamera: "Continue without gaze",
          declinedTitle: "Research declined", declinedDescription: "No study collection has started.",
          completeTitle: "Your choice is recorded", completeWithCameraDescription: "You agreed to camera use.",
          completeWithoutCameraDescription: "You can take part without gaze tracking.", withdrawnDescription: "Study collection has stopped.",
          withdraw: "Withdraw participation",
          withdrawing: "Stopping collection…", withdrawn: "Collection stopped and withdrawal was recorded.",
          withdrawnAuditUnavailable: "Collection stopped; the withdrawal signal could not be sent.",
          retryWithdrawalAudit: "Retry withdrawal record",
          saving: "Saving your choice…", saveFailed: "We could not securely save that choice. No collection has started.",
        },
      });
    });

    await page.getByRole("heading", { name: "Research participation consent" }).waitFor();
    await page.getByRole("button", { name: "Agree to research" }).click();
    await page.getByRole("heading", { name: "Camera and gaze consent" }).waitFor();
    assert.equal(await page.evaluate(() => window.controller.canCollectResearch), true);
    assert.equal(await page.evaluate(() => window.controller.canCaptureCamera), false);
    assert.deepEqual(await page.evaluate(() => window.consentRecords.map(({ scope, decision, policy_version }) => ({ scope, decision, policy_version }))), [
      { scope: "research_participation", decision: "accepted", policy_version: "research-policy-v7" },
    ]);

    await page.getByRole("button", { name: "Continue without gaze" }).click();
    await page.getByRole("heading", { name: "Your choice is recorded" }).waitFor();
    assert.equal(await page.evaluate(() => window.continuedWith.modality), "non_gaze_only");
    assert.deepEqual(await page.evaluate(() => window.consentRecords.map(({ scope, decision, policy_version }) => ({ scope, decision, policy_version }))), [
      { scope: "research_participation", decision: "accepted", policy_version: "research-policy-v7" },
      { scope: "camera_gaze", decision: "declined", policy_version: "camera-policy-v4" },
    ]);
    assert.equal(await page.evaluate(() => window.controller.canCollectResearch), true);
    assert.equal(await page.evaluate(() => window.controller.canCaptureCamera), false);

    await page.getByRole("button", { name: "Withdraw participation" }).click();
    await page.getByText("Collection stopped and withdrawal was recorded.").waitFor();
    assert.equal(await page.evaluate(() => window.auditSignals), 1);
    assert.equal(await page.evaluate(() => window.flow.state), "withdrawn");
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

test("camera denial offers recovery and non-gaze continuation without blocking the participant flow", async (t) => {
  let browser;
  try {
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_BIN || undefined, args: ["--no-sandbox"] });
    const page = await browser.newPage({ viewport: { width: 390, height: 760 } });
    await page.setContent("<!doctype html><html lang=\"en\"><body><main id=\"consent-root\"></main></body></html>");
    const lifecycleSource = fs.readFileSync(lifecycleModule, "utf8").replace("export class ConsentLifecycle", "class ConsentLifecycle") + "\nwindow.ConsentLifecycle = ConsentLifecycle;";
    const uiSource = fs.readFileSync(uiModule, "utf8").replace("export function mountConsentFlow", "function mountConsentFlow") + "\nwindow.mountConsentFlow = mountConsentFlow;";
    await page.addScriptTag({ content: lifecycleSource });
    await page.addScriptTag({ content: uiSource });
    await page.evaluate(() => {
      const policy = {
        research: { version: "r-v1", text: "Participation is optional." },
        camera: { version: "c-v1", text: "Camera tracking is optional.", offered: true },
      };
      window.controller = new window.ConsentLifecycle({ policy, persistConsent: async () => {}, flushWithdrawalAudit: async () => {} });
      window.flow = window.mountConsentFlow(document.querySelector("#consent-root"), {
        controller: window.controller,
        policy,
        onContinue: (result) => { window.continuedWith = result; },
        cameraOptions: {
          sessionId: "session-camera-ui",
          provider: { start: async ({ on_status }) => { on_status("unavailable", "gaze.permission_denied"); }, stop() {} },
          initialGeometry: { schema_version: "1.0.0" },
          onSample() {},
        },
        labels: {
          researchTitle: "Research participation consent", acceptResearch: "Agree to research", declineResearch: "Decline research",
          cameraTitle: "Camera and gaze consent", acceptCamera: "Agree to camera", declineCamera: "Continue without gaze",
          declinedTitle: "Research declined", declinedDescription: "No study collection has started.",
          completeTitle: "Your choice is recorded", completeWithCameraDescription: "You agreed to camera use.",
          completeWithoutCameraDescription: "Survey continues without gaze tracking.", cameraReadyToStart: "You can start camera tracking or continue without it.",
          startCamera: "Start camera", cameraStarting: "Checking camera…", cameraActive: "Camera tracking is active.",
          cameraDenied: "Camera access was denied. You can retry or continue without gaze.", cameraUnavailable: "Camera is unavailable.",
          cameraUnsupported: "This browser does not support camera access.", cameraInterrupted: "Camera capture was interrupted.",
          cameraUnplugged: "The camera was disconnected.", cameraRevoked: "Camera permission was revoked.", providerFailed: "Gaze tracking could not start.",
          retryCamera: "Retry camera", continueWithoutGaze: "Continue without gaze", withdrawnDescription: "Study collection has stopped.",
          withdraw: "Withdraw participation", withdrawing: "Stopping collection…", withdrawn: "Collection stopped.",
          withdrawnAuditUnavailable: "Collection stopped; the withdrawal signal could not be sent.", retryWithdrawalAudit: "Retry withdrawal record",
          saving: "Saving your choice…", saveFailed: "We could not securely save that choice.",
        },
      });
    });
    await page.getByRole("button", { name: "Agree to research" }).click();
    await page.getByRole("button", { name: "Agree to camera" }).click();
    await page.getByRole("button", { name: "Start camera" }).click();
    await page.getByText("Camera access was denied. You can retry or continue without gaze.").waitFor();
    assert.equal(await page.evaluate(() => window.controller.snapshot().camera.modality), "non_gaze_only");
    await page.getByRole("button", { name: "Continue without gaze" }).click();
    await page.getByText("Survey continues without gaze tracking.").waitFor();
    assert.equal(await page.evaluate(() => window.controller.canCollectResearch), true);
    assert.equal(await page.evaluate(() => window.flow.state), "complete");
    assert.equal(await page.evaluate(() => window.continuedWith.modality), "non_gaze_only");
    assert.equal(await page.evaluate(() => window.continuedWith.missingness), "gaze.permission_denied");
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
