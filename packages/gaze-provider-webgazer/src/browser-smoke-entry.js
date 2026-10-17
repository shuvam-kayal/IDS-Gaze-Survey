import { createWebGazerAdapter } from "./webgazer-adapter.js";
import {
  CALIBRATION_TARGETS,
  calibrationProgress,
  createCalibrationState,
  recordCalibrationClick,
} from "./calibration.js";

const consent = document.querySelector("#consent");
const startButton = document.querySelector("#start");
const stopButton = document.querySelector("#stop");
const restartCalibrationButton = document.querySelector("#restart-calibration");
const status = document.querySelector("#status");
const calibrationStatus = document.querySelector("#calibration-status");
const count = document.querySelector("#count");
const prediction = document.querySelector("#prediction");
const viewport = document.querySelector("#viewport");
const calibrationLayer = document.querySelector("#calibration-layer");
const callbackMarker = document.querySelector("#callback-marker");
const callbackCount = document.querySelector("#callback-count");
const nullCount = document.querySelector("#null-count");
const finiteCount = document.querySelector("#finite-count");
const invalidCount = document.querySelector("#invalid-count");
const latestFinite = document.querySelector("#latest-finite");
const sinceFinite = document.querySelector("#since-finite");
const mouseStationary = document.querySelector("#mouse-stationary");

let adapter = null;
let sampleCount = 0;
let calibration = null;
let diagnostics = null;
let mouseLastMoveAt = null;
let lastFiniteAt = null;

function setStatus(value, reason = "") {
  status.textContent = reason ? `${value}: ${reason}` : value;
}

function updateViewport() {
  viewport.textContent = `${window.innerWidth} × ${window.innerHeight}`;
  renderCalibrationTargets();
}

function resetDiagnostics() {
  diagnostics = { callbacks: 0, nulls: 0, finite: 0, invalid: 0 };
  mouseLastMoveAt = performance.now();
  lastFiniteAt = null;
  callbackCount.textContent = "0";
  nullCount.textContent = "0";
  finiteCount.textContent = "0";
  invalidCount.textContent = "0";
  latestFinite.textContent = "none";
  sinceFinite.textContent = "n/a";
  mouseStationary.textContent = "true";
  callbackMarker.style.display = "none";
}

function updateDiagnosticPanel() {
  if (!diagnostics) return;
  callbackCount.textContent = String(diagnostics.callbacks);
  nullCount.textContent = String(diagnostics.nulls);
  finiteCount.textContent = String(diagnostics.finite);
  invalidCount.textContent = String(diagnostics.invalid);
  mouseStationary.textContent = mouseLastMoveAt !== null && performance.now() - mouseLastMoveAt >= 1000 ? "true" : "false";
  sinceFinite.textContent = lastFiniteAt === null ? "n/a" : `${Math.round(performance.now() - lastFiniteAt)} ms`;
}

function displaySample(sample) {
  sampleCount += 1;
  count.textContent = String(sampleCount);
  prediction.textContent = [
    `valid=${sample.valid}`,
    `x_px=${sample.x_px === null ? "null" : sample.x_px}`,
    `y_px=${sample.y_px === null ? "null" : sample.y_px}`,
    `confidence=${sample.quality.confidence === null ? "null" : sample.quality.confidence}`,
    `flags=${sample.quality.flags.join(",") || "none"}`,
  ].join(" | ");

  if (!diagnostics) resetDiagnostics();
  diagnostics.callbacks += 1;
  if (sample.valid && Number.isFinite(sample.x_px) && Number.isFinite(sample.y_px)) {
    diagnostics.finite += 1;
    lastFiniteAt = performance.now();
    latestFinite.textContent = `(${sample.x_px.toFixed(1)}, ${sample.y_px.toFixed(1)})`;
    callbackMarker.style.left = `${sample.x_px}px`;
    callbackMarker.style.top = `${sample.y_px}px`;
    callbackMarker.style.display = "block";
  } else if (sample.x_px === null || sample.y_px === null) {
    diagnostics.nulls += 1;
  } else {
    diagnostics.invalid += 1;
  }
  updateDiagnosticPanel();
}

function renderCalibrationTargets() {
  if (!calibration || calibration.completed) {
    calibrationLayer.replaceChildren();
    return;
  }
  calibrationLayer.replaceChildren();
  const target = CALIBRATION_TARGETS[calibration.targetIndex];
  const button = document.createElement("button");
  button.type = "button";
  button.className = "calibration-target";
  button.title = `Look at the ${target.label} target, then click it`;
  button.setAttribute("aria-label", `Calibration target ${calibrationProgress(calibration)} at ${target.label}`);
  button.style.left = `${target.x * 100}%`;
  button.style.top = `${target.y * 100}%`;
  button.textContent = String(calibration.clicksByTarget[calibration.targetIndex] + 1);
  button.addEventListener("click", () => {
    recordCalibrationClick(calibration);
    if (calibration.completed) {
      calibrationLayer.replaceChildren();
      calibrationStatus.textContent = "procedure completed; accuracy not yet validated";
      setStatus("capturing predictions");
    } else {
      calibrationStatus.textContent = `${calibrationProgress(calibration)}; click target ${calibration.clicksByTarget[calibration.targetIndex] + 1}/${calibration.clicksPerTarget}`;
      renderCalibrationTargets();
    }
  });
  calibrationLayer.append(button);
  calibrationStatus.textContent = `${calibrationProgress(calibration)}; click target ${calibration.clicksByTarget[calibration.targetIndex] + 1}/${calibration.clicksPerTarget}`;
}

function beginCalibration() {
  calibration = createCalibrationState(3);
  calibrationStatus.textContent = "look directly at the target, then click it; 3 deliberate clicks per target";
  setStatus("calibrating");
  renderCalibrationTargets();
}

function restartCalibration() {
  if (!adapter) return;
  beginCalibration();
}

async function startCapture() {
  if (!consent.checked) {
    setStatus("blocked", "explicit consent is required");
    return;
  }
  if (adapter) return;
  sampleCount = 0;
  count.textContent = "0";
  prediction.textContent = "No prediction received yet.";
  resetDiagnostics();
  calibration = null;
  calibrationStatus.textContent = "camera not started";
  setStatus("starting");
  try {
    adapter = await createWebGazerAdapter({
      viewport: () => ({ width: window.innerWidth, height: window.innerHeight }),
    });
    // Hide WebGazer's internal smoothed point so the green marker below
    // unambiguously represents coordinates delivered to this callback.
    if (typeof adapter.api.showPredictionPoints === "function") {
      adapter.api.showPredictionPoints(false);
    }
    await adapter.start({
      session_id: "manual-webgazer-smoke-session",
      consent_granted: true,
      on_sample: displaySample,
      on_status: (value, reason) => {
        if (value === "initializing") setStatus("camera initializing");
        else if (value === "ready") setStatus("camera ready");
        else setStatus(value, reason);
      },
    });
    startButton.disabled = true;
    stopButton.disabled = false;
    restartCalibrationButton.disabled = false;
    beginCalibration();
  } catch {
    adapter = null;
    startButton.disabled = false;
    stopButton.disabled = true;
    restartCalibrationButton.disabled = true;
    calibrationStatus.textContent = "not available";
  }
}

function stopCapture() {
  if (!adapter) return;
  adapter.stop("manual_stop");
  adapter = null;
  calibration = null;
  calibrationLayer.replaceChildren();
  callbackMarker.style.display = "none";
  calibrationStatus.textContent = "stopped";
  startButton.disabled = !consent.checked;
  stopButton.disabled = true;
  restartCalibrationButton.disabled = true;
}

consent.addEventListener("change", () => {
  startButton.disabled = !consent.checked || Boolean(adapter);
});
startButton.addEventListener("click", startCapture);
stopButton.addEventListener("click", stopCapture);
restartCalibrationButton.addEventListener("click", restartCalibration);
window.addEventListener("mousemove", () => {
  mouseLastMoveAt = performance.now();
  updateDiagnosticPanel();
});
window.addEventListener("resize", updateViewport);
window.addEventListener("beforeunload", stopCapture);
window.setInterval(updateDiagnosticPanel, 250);
updateViewport();
resetDiagnostics();
setStatus("idle", "provider-only smoke test; no P1 integration");
