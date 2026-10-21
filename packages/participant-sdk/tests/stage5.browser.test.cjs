const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const geometryModule = path.resolve(__dirname, "../src/geometry.js");

test("browser geometry snapshots follow resize, scroll, zoom and DOM reflow in contract viewport pixels", async (t) => {
  let browser;
  try {
    browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_BIN || undefined, args: ["--no-sandbox"] });
    const page = await browser.newPage({ viewport: { width: 800, height: 600 } });
    await page.setContent(`<!doctype html><html><head><style>
      html,body { margin:0; min-height:2200px }
      #target { position:absolute; left:100px; top:120px; width:60px; height:40px; }
      #hidden { display:none; width:20px; height:20px }
      @media (max-width: 700px) { #target { left:30px; width:45px; } }
    </style></head><body><div id="target"></div><div id="hidden"></div></body></html>`);
    let source = fs.readFileSync(geometryModule, "utf8");
    source = source.replace("export function parseAoiConfig", "function parseAoiConfig")
      .replace("export function resolveAoiIdForTarget", "function resolveAoiIdForTarget")
      .replace("export function createGeometryTracker", "function createGeometryTracker")
      + "\nwindow.GeometrySdk = { parseAoiConfig, resolveAoiIdForTarget, createGeometryTracker };";
    await page.addScriptTag({ content: source });
    await page.evaluate(() => {
      window.geometrySnapshots = [];
      const listeners = new Map();
      window.testVisualViewport = {
        scale: 1,
        addEventListener(name, listener) { const values = listeners.get(name) || new Set(); values.add(listener); listeners.set(name, values); },
        removeEventListener(name, listener) { listeners.get(name)?.delete(listener); },
        fire(name) { for (const listener of listeners.get(name) || []) listener(new Event(name)); },
      };
      const fakeWindow = {
        get innerWidth() { return window.innerWidth; },
        get innerHeight() { return window.innerHeight; },
        get scrollX() { return window.scrollX; },
        get scrollY() { return window.scrollY; },
        visualViewport: window.testVisualViewport,
        getComputedStyle: window.getComputedStyle.bind(window),
        addEventListener: window.addEventListener.bind(window),
        removeEventListener: window.removeEventListener.bind(window),
      };
      const controller = {
        registerListener(target, name, listener, options) { target.addEventListener(name, listener, options); return () => true; },
        registerCollector() { return () => true; },
      };
      window.geometryTracker = window.GeometrySdk.createGeometryTracker({
        aoiConfig: {
          schema_version: "1.0.0", experience_id: "exp-1", study_id: "study-1", aoi_set_version: "aoi-v7",
          aois: [
            { aoi_id: "aoi-target", label: "Target", selector: "#target", tracking_strategy: "css_selector", priority: 4, enabled: true },
            { aoi_id: "aoi-priority", label: "Target overlap", selector: "#target", tracking_strategy: "css_selector", priority: 9, enabled: true },
            { aoi_id: "aoi-hidden", label: "Hidden", selector: "#hidden", tracking_strategy: "css_selector", priority: 1, enabled: true },
          ],
        },
        context: { experience_id: "exp-1", study_id: "study-1", session_id: "session-1" },
        controller, window: fakeWindow, document,
        wallClock: () => new Date("2026-08-09T10:11:12.000Z"), snapshotId: (() => { let n = 0; return () => `snapshot-${++n}`; })(),
        debounceMs: 5, onSnapshot: (snapshot) => window.geometrySnapshots.push(snapshot),
      });
      window.initialGeometry = window.geometryTracker.start();
    });
    const initial = await page.evaluate(() => window.initialGeometry);
    assert.deepEqual(Object.keys(initial), ["schema_version", "snapshot_id", "session_id", "study_id", "captured_at", "aoi_set_version", "viewport_width_px", "viewport_height_px", "scroll_x_px", "scroll_y_px", "zoom", "rectangles"]);
    assert.equal(initial.schema_version, "2.0.0");
    assert.equal(initial.captured_at, "2026-08-09T10:11:12.000Z");
    assert.equal(initial.viewport_width_px, 800);
    assert.equal(initial.rectangles.length, 2, "hidden elements are excluded");
    assert.deepEqual(initial.rectangles[0], { aoi_id: "aoi-target", left_px: 100, top_px: 120, right_px: 160, bottom_px: 160, priority: 4 });
    assert.equal(await page.evaluate(() => window.geometryTracker.resolveTarget(document.querySelector("#target"))), "aoi-priority");

    await page.setViewportSize({ width: 600, height: 600 });
    await page.waitForFunction(() => window.geometrySnapshots.at(-1).viewport_width_px === 600 && window.geometrySnapshots.at(-1).rectangles[0].left_px === 30);
    const resized = await page.evaluate(() => window.geometrySnapshots.at(-1));
    assert.equal(resized.rectangles[0].right_px - resized.rectangles[0].left_px, 45);

    await page.evaluate(() => {
      document.querySelector("#target").style.height = "85px";
    });
    await page.waitForFunction(() => window.geometrySnapshots.at(-1).rectangles[0].bottom_px - window.geometrySnapshots.at(-1).rectangles[0].top_px === 85);

    await page.evaluate(() => window.scrollTo(0, 300));
    await page.waitForFunction(() => window.geometrySnapshots.at(-1).scroll_y_px === 300);
    const scrolled = await page.evaluate(() => window.geometrySnapshots.at(-1));
    assert.equal(scrolled.rectangles[0].top_px, -180);

    await page.evaluate(() => {
      window.testVisualViewport.scale = 1.5;
      window.testVisualViewport.fire("resize");
    });
    await page.waitForFunction(() => window.geometrySnapshots.at(-1).zoom === 1.5);
    assert.equal((await page.evaluate(() => window.geometrySnapshots.at(-1))).rectangles[0].top_px, -180);

    await page.evaluate(() => {
      document.querySelector("#target").remove();
    });
    await page.waitForFunction(() => window.geometrySnapshots.at(-1).rectangles.length === 0);
    await page.evaluate(() => window.geometryTracker.stop());
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
