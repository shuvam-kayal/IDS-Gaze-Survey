/**
 * P3-owned WebGazer boundary.
 *
 * This module emits only the frozen ProviderSample shape. It never forwards
 * WebGazer-native objects, video frames, or error objects to callers.
 */

export const WEBGAZER_VERSION = "3.5.3";

const STATUS = Object.freeze({
  INITIALIZING: "initializing",
  READY: "ready",
  UNAVAILABLE: "unavailable",
  STOPPED: "stopped",
});

function isFiniteNonNegative(value) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function utcTimestamp(startedAtMs, captureTimeMs) {
  return new Date(startedAtMs + captureTimeMs).toISOString();
}

function safeStatus(callback, status, reason) {
  try {
    callback(status, reason);
  } catch {
    // A consumer callback must not break provider cleanup.
  }
}

function providerReason(error) {
  return error && (error.name === "NotAllowedError" || error.name === "PermissionDeniedError")
    ? "gaze.permission_denied"
    : "gaze.provider_failure";
}

/**
 * Adapter around the small public WebGazer API used by this project.
 *
 * The `api` argument is injectable so tests can exercise lifecycle behavior
 * without a webcam or a browser. Production construction dynamically imports
 * the pinned npm package through `createWebGazerAdapter`.
 */
export class WebGazerAdapter {
  constructor(api, { clock = () => Date.now(), viewport = () => ({
    width: globalThis.innerWidth,
    height: globalThis.innerHeight,
  }) } = {}) {
    this.api = api;
    this.clock = clock;
    this.viewport = viewport;
    this.active = false;
    this.sessionId = null;
    this.startedAtMs = null;
    this.sequence = 0;
    this.onStatus = () => {};
  }

  async start(input) {
    if (!input || input.consent_granted !== true) {
      throw new Error("WebGazer start requires explicit consent_granted=true");
    }
    if (typeof input.session_id !== "string" || input.session_id.length === 0) {
      throw new Error("session_id must be a non-empty string");
    }
    if (typeof input.on_sample !== "function" || typeof input.on_status !== "function") {
      throw new Error("on_sample and on_status callbacks are required");
    }
    if (this.active) {
      if (this.sessionId !== input.session_id) {
        throw new Error("WebGazer is already active for another session");
      }
      return;
    }
    this.active = true;
    this.sessionId = input.session_id;
    this.startedAtMs = this.clock();
    this.sequence = 0;
    this.onStatus = input.on_status;
    safeStatus(this.onStatus, STATUS.INITIALIZING);

    const listener = (prediction, elapsedTime) => {
      if (!this.active) return;
      this.emitSample(input.on_sample, prediction, elapsedTime);
    };
    this.listener = listener;

    try {
      // WebGazer persists calibration by default; disable it for session
      // isolation before beginning capture.
      this.api.saveDataAcrossSessions(false);
      this.api.setGazeListener(listener);
      await this.api.begin();
      if (this.active) safeStatus(this.onStatus, STATUS.READY);
    } catch (error) {
      const reason = providerReason(error);
      this.cleanupApi();
      this.active = false;
      this.sessionId = null;
      safeStatus(this.onStatus, STATUS.UNAVAILABLE, reason);
      throw new Error(reason);
    }
  }

  emitSample(onSample, prediction, elapsedTime) {
    const clockDelta = this.clock() - this.startedAtMs;
    const captureTimeMs = isFiniteNonNegative(elapsedTime)
      ? elapsedTime
      : Math.max(0, Number.isFinite(clockDelta) ? clockDelta : 0);
    const flags = ["gaze.calibration_unverified"];
    let xPx = null;
    let yPx = null;
    let valid = false;
    const viewport = this.viewport();
    const width = viewport && viewport.width;
    const height = viewport && viewport.height;

    if (prediction === null || prediction === undefined) {
      flags.push("provider.prediction_missing");
    } else if (!Number.isFinite(prediction.x) || !Number.isFinite(prediction.y)) {
      flags.push("provider.prediction_invalid");
    } else if (!isFiniteNonNegative(width) || !isFiniteNonNegative(height) || width === 0 || height === 0) {
      flags.push("provider.viewport_invalid");
    } else if (prediction.x < 0 || prediction.x > width || prediction.y < 0 || prediction.y > height) {
      flags.push("provider.prediction_out_of_bounds");
    } else {
      xPx = prediction.x;
      yPx = prediction.y;
      valid = true;
    }

    const sample = {
      schema_version: "1.0.0",
      provider: "webgazer",
      provider_version: WEBGAZER_VERSION,
      sample_id: `${this.sessionId}:webgazer:${this.sequence++}`,
      capture_time_ms: captureTimeMs,
      occurred_at: utcTimestamp(this.startedAtMs, captureTimeMs),
      x_px: xPx,
      y_px: yPx,
      valid,
      quality: { confidence: null, flags },
    };
    try {
      onSample(sample);
    } catch {
      // Consumer failures cannot leave WebGazer running without cleanup.
      this.stop("gaze.capture_interrupted");
    }
  }

  stop(reason = "gaze.capture_interrupted") {
    if (!this.active) return;
    this.cleanupApi();
    this.active = false;
    this.sessionId = null;
    safeStatus(this.onStatus, STATUS.STOPPED, reason);
  }

  cleanupApi() {
    try {
      if (typeof this.api.clearGazeListener === "function") this.api.clearGazeListener();
      if (typeof this.api.end === "function") {
        const result = this.api.end();
        if (result && typeof result.catch === "function") result.catch(() => {});
      }
    } catch {
      // Cleanup is best effort and must not expose provider objects.
    }
    this.listener = null;
  }
}

export async function createWebGazerAdapter(options) {
  const module = await import("webgazer");
  return new WebGazerAdapter(module.default ?? module, options);
}

export { STATUS as WEBGAZER_STATUS };
