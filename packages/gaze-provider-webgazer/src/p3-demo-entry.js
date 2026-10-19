import { createWebGazerAdapter } from "./webgazer-adapter.js";

const mode = document.querySelector("#mode");
const consent = document.querySelector("#consent");
const startCamera = document.querySelector("#start-camera");
const stopCamera = document.querySelector("#stop-camera");
const submit = document.querySelector("#submit");
const reset = document.querySelector("#reset");
const scenario = document.querySelector("#scenario");
const status = document.querySelector("#status");
const output = document.querySelector("#output");
const report = document.querySelector("#report");
const cameraError = document.querySelector("#camera-error");
let config;
let adapter;
let captured = [];

const setStatus = (value) => { status.textContent = value; };
const show = (value) => { output.textContent = JSON.stringify(value, null, 2); };

function syntheticSamples() {
  return [0, 100, 200].map((offset, index) => ({
    schema_version: "1.0.0",
    provider: "synthetic-provider",
    provider_version: "local-demo-1",
    sample_id: `demo-sample-${index}`,
    capture_time_ms: offset,
    occurred_at: new Date(Date.parse(config.window_start) + 1000 + offset).toISOString(),
    x_px: 25,
    y_px: 25,
    valid: true,
    quality: { confidence: 0.9, flags: [] },
  }));
}

async function load() {
  config = await (await fetch("/__p3_demo/config")).json();
  show({ stage: "fixture-loaded", config });
  setStatus("fixture loaded; choose a mode");
}

async function startCameraCapture() {
  if (!consent.checked) { setStatus("blocked: explicit demo consent is required"); return; }
  try {
    cameraError.textContent = "";
    adapter = await createWebGazerAdapter({
      viewport: () => ({ width: window.innerWidth, height: window.innerHeight }),
    });
    captured = [];
    await adapter.start({
      session_id: config.session_id,
      consent_granted: true,
      initial_geometry: {
        schema_version: "1.0.0", snapshot_id: "local-demo-browser-geometry",
        session_id: config.session_id, captured_at: new Date().toISOString(),
        aoi_set_version: config.aoi_set_version, viewport_width_px: window.innerWidth,
        viewport_height_px: window.innerHeight, scroll_x_px: 0, scroll_y_px: 0,
        zoom: window.devicePixelRatio || 1, rectangles: [],
      },
      on_sample: (sample) => { if (captured.length < 250) captured.push(sample); show({ stage: "capturing", sample_count: captured.length, latest: sample }); },
      on_status: (value, reason) => setStatus(reason ? `${value}: ${reason}` : value),
    });
    stopCamera.disabled = false;
    submit.disabled = false;
  } catch (error) {
    cameraError.textContent = `Initialization error: ${error.message}`;
    setStatus(`camera unavailable: ${error.message}`);
  }
}

function stopCameraCapture() {
  if (adapter) adapter.stop("local_demo_stop");
  adapter = null;
  setStatus("camera stopped; captured samples remain temporary");
}

async function submitObservation() {
  const selected = scenario.value;
  let samples = mode.value === "synthetic" ? syntheticSamples() : captured.map((sample) => ({
    ...sample,
    // The fixture uses a 100x100 viewport. This is an explicit demo-only
    // coordinate transform, not a gaze estimate or calibration claim.
    x_px: sample.x_px === null ? null : sample.x_px * 100 / window.innerWidth,
    y_px: sample.y_px === null ? null : sample.y_px * 100 / window.innerHeight,
  }));
  const requestId = `${selected}-${selected === "retry" ? "same" : Date.now()}`;
  if (selected === "camera-denied") samples = [];
  if (selected === "invalid-sample") samples = syntheticSamples().map((sample) => ({ ...sample, x_px: 999 }));
  const response = await fetch("/v1/gaze/observations", {
    method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ schema_version: "1.0.0", request_id: requestId, session_id: config.session_id, provider_samples: samples }),
  });
  const body = await response.json();
  show({ stage: "submission", http_status: response.status, response: body, sample_count: samples.length });
  setStatus(response.ok ? `processed: ${body.status}` : `rejected: ${body.error?.code || response.status}`);
  await refreshReport();
}

async function refreshReport() {
  report.textContent = JSON.stringify(await (await fetch("/__p3_demo/report")).json(), null, 2);
}

async function resetDemo() {
  stopCameraCapture();
  show(await (await fetch("/__p3_demo/reset", { method: "POST" })).json());
  await refreshReport();
  setStatus("dedicated demo session reset");
}

mode.addEventListener("change", () => { startCamera.disabled = mode.value !== "camera"; submit.disabled = mode.value === "camera"; });
startCamera.addEventListener("click", startCameraCapture);
stopCamera.addEventListener("click", stopCameraCapture);
submit.addEventListener("click", submitObservation);
reset.addEventListener("click", resetDemo);
load();
