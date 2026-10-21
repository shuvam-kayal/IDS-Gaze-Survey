import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const packageRoot = fileURLToPath(new URL("..", import.meta.url));
const smokePage = join(packageRoot, "smoke-test", "index.html");
const p3DemoPage = join(packageRoot, "smoke-test", "p3-demo.html");
const p3DemoEntry = join(packageRoot, "src", "p3-demo-entry.js");

test("smoke page reserves a control region above the WebGazer preview", async () => {
  const html = await readFile(smokePage, "utf8");

  assert.match(
    html,
    /<main id="smoke-controls">[\s\S]*id="capture-controls"[\s\S]*id="diagnostic-controls"[\s\S]*<\/main>/,
  );
  assert.match(html, /#capture-controls\s*\{[\s\S]*z-index:\s*3000/);
  assert.match(html, /#calibration-layer\s*\{[\s\S]*z-index:\s*2000/);
  assert.match(html, /#diagnostic-controls\s*\{[\s\S]*z-index:\s*1000/);
  assert.match(html, /#webgazerVideoContainer\s*\{[\s\S]*pointer-events:\s*none/);
  assert.match(html, /#webgazerVideoContainer \*, #webgazerGazeDot\s*\{[\s\S]*pointer-events:\s*none/);
  assert.match(html, /id="stop"/);
  assert.match(html, /id="calibration-layer"/);
});

test("smoke page keeps the optional preview out of the control flow on small viewports", async () => {
  const html = await readFile(smokePage, "utf8");

  assert.match(html, /@media \(max-width: 700px\), \(max-height: 520px\)/);
  assert.match(html, /#webgazerVideoContainer\s*\{\s*display:\s*none !important;/);
});

test("P3 demo keeps fallback and camera errors explicit", async () => {
  const html = await readFile(p3DemoPage, "utf8");
  const source = await readFile(p3DemoEntry, "utf8");

  assert.match(html, /id="reset"/);
  assert.match(html, /value="camera-denied"/);
  assert.match(html, /id="camera-error"/);
  assert.match(source, /if \(selected === "camera-denied"\) samples = \[\];/);
  assert.match(source, /Initialization error:/);
});
