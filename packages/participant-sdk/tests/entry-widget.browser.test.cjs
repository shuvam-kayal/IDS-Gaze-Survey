const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const entryModule = path.resolve(__dirname, "../src/entry-widget.js");

test("browser decline is keyboard accessible and creates no session or research telemetry", async (t) => {
  let browser;
  try {
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_BIN || undefined, args: ["--no-sandbox"] });
    const page = await browser.newPage({ viewport: { width: 360, height: 740 } });
    await page.setContent("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Entry widget test</title></head><body><main id=\"participant-root\"></main></body></html>");
    const runtime = fs.readFileSync(entryModule, "utf8")
      .replace("export function mountParticipantEntry", "function mountParticipantEntry")
      + "\nwindow.mountParticipantEntry = mountParticipantEntry;";
    await page.addScriptTag({ content: runtime });
    await page.evaluate(async () => {
      window.sideEffects = { sessionRequests: 0, researchEvents: 0, accepts: 0 };
      window.widget = window.mountParticipantEntry(document.querySelector("#participant-root"), {
        experienceId: "experience-synthetic",
        invitation: {
          title: "Research invitation", description: "Optional study participation.", buttonLabel: "Review invitation",
          acceptLabel: "Accept invitation", declineLabel: "Decline", declinedTitle: "Invitation declined",
          declinedDescription: "You can close this message.", closeLabel: "Close", startingLabel: "Starting",
          errorMessage: "Unable to continue. Try again later.",
        },
        onAccept: async () => {
          window.sideEffects.accepts += 1;
          window.sideEffects.sessionRequests += 1;
          window.sideEffects.researchEvents += 1;
        },
      });
    });

    await page.getByRole("button", { name: "Review invitation" }).focus();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog", { name: "Research invitation" });
    await dialog.waitFor({ state: "visible" });
    assert.ok((await dialog.boundingBox()).width <= 360);
    await page.getByRole("button", { name: "Decline" }).focus();
    await page.keyboard.press("Enter");
    await page.getByText("No session was started.").waitFor();

    assert.equal(await page.evaluate(() => window.widget.state), "declined");
    assert.deepEqual(await page.evaluate(() => window.sideEffects), { sessionRequests: 0, researchEvents: 0, accepts: 0 });
    assert.match(await page.getByRole("dialog").getAttribute("aria-describedby"), /^ids-entry-\d+-description$/);
    await page.getByRole("button", { name: "Close" }).click();
    assert.equal(await page.evaluate(() => document.activeElement.textContent), "Review invitation");
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
