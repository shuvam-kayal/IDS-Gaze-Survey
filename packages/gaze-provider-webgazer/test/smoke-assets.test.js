import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { MEDIAPIPE_FACE_MESH_ASSETS, copyMediaPipeAssets } from "../smoke-test/copy-mediapipe-assets.mjs";
import { createSmokeServer } from "../smoke-test/server.mjs";

const packageRoot = fileURLToPath(new URL("..", import.meta.url));

test("local smoke server serves every pinned FaceMesh runtime asset", async () => {
  execFileSync(process.execPath, ["smoke-test/copy-mediapipe-assets.mjs"], { cwd: packageRoot });
  await copyMediaPipeAssets();
  const server = createSmokeServer();
  await new Promise((resolve) => server.listen(0, "localhost", resolve));
  const address = server.address();
  const port = typeof address === "object" && address ? address.port : 0;
  try {
    for (const asset of MEDIAPIPE_FACE_MESH_ASSETS) {
      const response = await fetch(`http://localhost:${port}/mediapipe/face_mesh/${asset}`);
      assert.equal(response.status, 200, asset);
      assert.ok((await response.arrayBuffer()).byteLength > 0, asset);
    }
  } finally {
    await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }
});

test("local smoke server serves the built P3 demo entry", async () => {
  const server = createSmokeServer();
  await new Promise((resolve) => server.listen(0, "localhost", resolve));
  const address = server.address();
  const port = typeof address === "object" && address ? address.port : 0;
  try {
    const response = await fetch(`http://localhost:${port}/p3-demo.js`);
    assert.equal(response.status, 200);
    assert.match(await response.text(), /createWebGazerAdapter|webgazer/);
  } finally {
    await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }
});
