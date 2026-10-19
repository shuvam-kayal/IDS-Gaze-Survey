const test = require("node:test");
const assert = require("node:assert/strict");

test("AOI config validates selector and identity contract and resolves priority ties deterministically", async () => {
  const { parseAoiConfig, resolveAoiIdForTarget } = await import("../src/geometry.js");
  const config = {
    schema_version: "1.0.0", experience_id: "exp-1", study_id: "study-1", aoi_set_version: "aoi-v3",
    aois: [
      { aoi_id: "z-region", label: "Z", selector: ".region", tracking_strategy: "css_selector", priority: 7 },
      { aoi_id: "a-region", label: "A", selector: ".region", tracking_strategy: "css_selector", priority: 7 },
      { aoi_id: "disabled", label: "Disabled", selector: "#disabled", tracking_strategy: "css_selector", priority: 100, enabled: false },
    ],
  };
  const parsed = parseAoiConfig(config);
  assert.equal(parsed.aoi_set_version, "aoi-v3");
  const target = { closest: (selector) => selector === ".region" ? {} : null };
  assert.equal(resolveAoiIdForTarget(target, parsed), "a-region", "equal-priority ties use deterministic lexical AOI identity");
  assert.throws(() => parseAoiConfig({ ...config, schema_version: "2.0.0" }), /Unsupported AOIConfig/);
  assert.throws(() => parseAoiConfig({ ...config, aois: [config.aois[0], config.aois[0]] }), /Duplicate AOI ID/);
});
