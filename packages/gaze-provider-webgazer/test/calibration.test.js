import test from "node:test";
import assert from "node:assert/strict";

import {
  CALIBRATION_TARGETS,
  calibrationProgress,
  createCalibrationState,
  recordCalibrationClick,
} from "../src/calibration.js";

test("calibration targets cover corners, edge centers, and center", () => {
  assert.equal(CALIBRATION_TARGETS.length, 9);
  assert.deepEqual(CALIBRATION_TARGETS.map(({ label }) => label), [
    "top-left", "top-center", "top-right",
    "middle-left", "center", "middle-right",
    "bottom-left", "bottom-center", "bottom-right",
  ]);
});

test("calibration advances only after the configured deliberate clicks", () => {
  const state = createCalibrationState(3);
  assert.equal(calibrationProgress(state), "1/9");
  recordCalibrationClick(state);
  recordCalibrationClick(state);
  assert.equal(state.targetIndex, 0);
  recordCalibrationClick(state);
  assert.equal(state.targetIndex, 1);
  assert.equal(state.clicksByTarget[0], 3);
});

test("calibration completion is deterministic and ignores later clicks", () => {
  const state = createCalibrationState(1);
  for (let index = 0; index < CALIBRATION_TARGETS.length; index += 1) {
    recordCalibrationClick(state);
  }
  assert.equal(state.completed, true);
  assert.equal(calibrationProgress(state), "9/9");
  const snapshot = JSON.stringify(state);
  recordCalibrationClick(state);
  assert.equal(JSON.stringify(state), snapshot);
});
