const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const demoDir = path.resolve(__dirname, "../../../apps/participant-demo");
const repoRoot = path.resolve(demoDir, "../..");

async function serveDemoRoutes(page) {
  await page.route("http://localhost:5173/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    const file = pathname.startsWith("/packages/participant-sdk/src/")
      ? path.resolve(repoRoot, `.${pathname}`)
      : path.resolve(demoDir, `.${pathname === "/" ? "/index.html" : pathname}`);
    if (!file.startsWith(repoRoot) || !fs.existsSync(file)) return route.fulfill({ status: 404, body: "not found" });
    const extension = path.extname(file);
    const contentType = extension === ".js" ? "text/javascript" : extension === ".css" ? "text/css" : extension === ".json" ? "application/json" : "text/html";
    return route.fulfill({ status: 200, contentType, body: fs.readFileSync(file) });
  });
  await page.route("http://localhost:8000/v1/events", async (route) => {
    const event = route.request().postDataJSON();
    await route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify({ schema_version: "1.0.0", event_id: event.event_id, status: "accepted", duplicate: false, ingested_at: "2026-10-19T10:00:00Z" }) });
  });
  await page.route("**/favicon.ico", (route) => route.fulfill({ status: 204, body: "" }));
}

test("participant demo completes decline and non-gaze study journeys without browser errors", async (t) => {
  let browser; let page; let errors = [];
  try {
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_BIN || undefined, args: ["--no-sandbox"] });
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
    await context.addInitScript(() => {
      Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: {
        getUserMedia: async () => { throw new DOMException("Permission denied for test", "NotAllowedError"); },
        addEventListener() {}, removeEventListener() {},
      } });
    });
    page = await context.newPage();
    page.setDefaultTimeout(6000);
    errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
    page.on("requestfailed", (request) => errors.push(`${request.url()}: ${request.failure()?.errorText}`));
    await serveDemoRoutes(page);
    await page.goto("http://localhost:5173", { waitUntil: "networkidle", timeout: 10000 });

    await page.getByRole("button", { name: "View study invitation" }).click();
    await page.getByRole("button", { name: "Decline", exact: true }).click();
    await page.getByText("You have not joined the study. No session was started.").waitFor();
    await page.getByRole("button", { name: "Close" }).click();
    await page.getByRole("button", { name: "View study invitation" }).click();
    await page.getByRole("button", { name: "Continue", exact: true }).click();
    await page.getByRole("button", { name: "I agree to participate" }).click();
    await page.getByRole("button", { name: "I agree to optional camera use" }).click();
    await page.getByRole("button", { name: "Request camera and start provider" }).click();
    await page.getByRole("button", { name: "Continue without gaze" }).click();
    await page.getByRole("button", { name: "Start trial" }).click();
    await page.getByRole("button", { name: "Finish trial" }).click();
    await page.getByRole("radio", { name: "Very clear" }).check();
    await page.getByRole("button", { name: "Submit sample answers" }).click();
    await page.getByText(/saved in this page only/).waitFor();
    await page.waitForTimeout(100);
    assert.deepEqual(errors, []);
  } catch (error) {
    if (/Executable doesn't exist|spawn .* ENOENT/.test(String(error))) {
      t.skip(`Python and a local Chromium executable are required for this smoke test: ${error.message}`);
      return;
    }
    const body = page ? await page.locator("body").innerText().catch(() => "") : "";
    throw new Error(`${error.message}\nBrowser errors: ${JSON.stringify(errors)}\nPage: ${body}`);
  } finally {
    if (browser) await browser.close();
  }
});

test("demo initializes only an injected provider after both consents on camera grant", async (t) => {
  let browser; let page; const errors = [];
  try {
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_BIN || undefined, args: ["--no-sandbox"] });
    const context = await browser.newContext({ viewport: { width: 800, height: 900 } });
    await context.addInitScript(() => {
      const track = { readyState: "live", addEventListener() {}, removeEventListener() {}, stop() { this.readyState = "ended"; } };
      Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: {
        getUserMedia: async () => ({ getTracks: () => [track], getVideoTracks: () => [track] }),
        addEventListener() {}, removeEventListener() {},
      } });
      window.providerStartCount = 0;
      window.adapterReceivedOnlyCapability = false;
      window.IDS_GAZE_PROVIDER = {
        async start(input) {
          window.providerStartCount++;
          window.adapterReceivedOnlyCapability = Boolean(input.camera_source && !("camera_stream" in input) && input.camera_source.getVideoTrack() === track);
          input.on_status("ready");
        },
        async stop() {},
      };
    });
    page = await context.newPage();
    page.setDefaultTimeout(6000);
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()); });
    await serveDemoRoutes(page);
    await page.goto("http://localhost:5173", { waitUntil: "networkidle", timeout: 10000 });
    await page.getByRole("button", { name: "View study invitation" }).click();
    await page.getByRole("button", { name: "Continue", exact: true }).click();
    await page.getByRole("button", { name: "I agree to participate" }).click();
    await page.getByRole("button", { name: "I agree to optional camera use" }).click();
    await page.getByRole("button", { name: "Request camera and start provider" }).click();
    await page.getByText("Camera and gaze provider are active.").waitFor();
    assert.equal(await page.evaluate(() => window.providerStartCount), 1);
    assert.equal(await page.evaluate(() => window.adapterReceivedOnlyCapability), true);
    await page.getByRole("button", { name: "Start trial" }).waitFor();
    assert.deepEqual(errors, []);
  } catch (error) {
    if (/Executable doesn't exist|spawn .* ENOENT/.test(String(error))) { t.skip(`A local Chromium executable is required for this smoke test: ${error.message}`); return; }
    throw new Error(`${error.message}\nBrowser errors: ${JSON.stringify(errors)}\nPage: ${page ? await page.locator("body").innerText().catch(() => "") : ""}`);
  } finally { if (browser) await browser.close(); }
});
