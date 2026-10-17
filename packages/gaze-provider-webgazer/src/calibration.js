/**
 * Test-only guided calibration procedure.
 *
 * This tracks deliberate target clicks; it does not claim that WebGazer has
 * calibrated successfully or provide an accuracy measurement.
 */

export const CALIBRATION_TARGETS = Object.freeze([
  Object.freeze({ x: 0.08, y: 0.12, label: "top-left" }),
  Object.freeze({ x: 0.50, y: 0.12, label: "top-center" }),
  Object.freeze({ x: 0.92, y: 0.12, label: "top-right" }),
  Object.freeze({ x: 0.08, y: 0.50, label: "middle-left" }),
  Object.freeze({ x: 0.50, y: 0.50, label: "center" }),
  Object.freeze({ x: 0.92, y: 0.50, label: "middle-right" }),
  Object.freeze({ x: 0.08, y: 0.88, label: "bottom-left" }),
  Object.freeze({ x: 0.50, y: 0.88, label: "bottom-center" }),
  Object.freeze({ x: 0.92, y: 0.88, label: "bottom-right" }),
]);

export function createCalibrationState(clicksPerTarget = 3) {
  if (!Number.isInteger(clicksPerTarget) || clicksPerTarget < 1) {
    throw new Error("clicksPerTarget must be a positive integer");
  }
  return {
    clicksPerTarget,
    targetIndex: 0,
    clicksByTarget: Array(CALIBRATION_TARGETS.length).fill(0),
    completed: false,
  };
}

export function recordCalibrationClick(state) {
  if (state.completed) return state;
  state.clicksByTarget[state.targetIndex] += 1;
  if (state.clicksByTarget[state.targetIndex] >= state.clicksPerTarget) {
    state.targetIndex += 1;
    state.completed = state.targetIndex === CALIBRATION_TARGETS.length;
  }
  return state;
}

export function calibrationProgress(state) {
  if (state.completed) return `${CALIBRATION_TARGETS.length}/${CALIBRATION_TARGETS.length}`;
  return `${state.targetIndex + 1}/${CALIBRATION_TARGETS.length}`;
}
