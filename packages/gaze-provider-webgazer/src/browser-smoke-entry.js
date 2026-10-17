import { createWebGazerAdapter } from "./webgazer-adapter.js";

const consent = document.querySelector("#consent");
const startButton = document.querySelector("#start");
const stopButton = document.querySelector("#stop");
const status = document.querySelector("#status");
const count = document.querySelector("#count");
const prediction = document.querySelector("#prediction");
const viewport = document.querySelector("#viewport");

let adapter = null;
let sampleCount = 0;

function setStatus(value, reason = "") {
  status.textContent = reason ? `${value}: ${reason}` : value;
}

function updateViewport() {
  viewport.textContent = `${window.innerWidth} × ${window.innerHeight}`;
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
  setStatus("starting");
  try {
    adapter = await createWebGazerAdapter({
      viewport: () => ({ width: window.innerWidth, height: window.innerHeight }),
    });
    await adapter.start({
      session_id: "manual-webgazer-smoke-session",
      consent_granted: true,
      on_sample: displaySample,
      on_status: setStatus,
    });
    startButton.disabled = true;
    stopButton.disabled = false;
  } catch {
    adapter = null;
    startButton.disabled = false;
    stopButton.disabled = true;
  }
}

function stopCapture() {
  if (!adapter) return;
  adapter.stop("manual_stop");
  adapter = null;
  startButton.disabled = false;
  stopButton.disabled = true;
}

consent.addEventListener("change", () => {
  startButton.disabled = !consent.checked;
});
startButton.addEventListener("click", startCapture);
stopButton.addEventListener("click", stopCapture);
window.addEventListener("resize", updateViewport);
window.addEventListener("beforeunload", stopCapture);
updateViewport();
setStatus("idle", "provider-only smoke test; no P1 integration");
