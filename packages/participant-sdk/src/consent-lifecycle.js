function nonEmptyString(value) {
  return typeof value === "string" && value.trim().length > 0;
}

function makeConsentPolicy(policy) {
  if (!policy || typeof policy !== "object") throw new TypeError("A server-provided consent policy is required");
  for (const scope of ["research", "camera"]) {
    if (!policy[scope] || !nonEmptyString(policy[scope].version)) {
      throw new TypeError(`Consent policy ${scope}.version is required`);
    }
  }
  if (!nonEmptyString(policy.research.text) || !nonEmptyString(policy.camera.text)) {
    throw new TypeError("Consent policy text is required for each separate choice");
  }
  if (typeof policy.camera.offered !== "boolean") throw new TypeError("Consent policy camera.offered must be a boolean");
  return policy;
}

function decisionRecord(scope, decision, policyVersion, occurredAt) {
  return Object.freeze({ scope, decision, policy_version: policyVersion, occurred_at: occurredAt });
}

/**
 * Consent decisions stay in memory and are sent only to the host's consent
 * persistence capability. No localStorage, event queue, or telemetry client is
 * used by this lifecycle controller.
 */
export class ConsentLifecycle {
  constructor({ policy, persistConsent, flushWithdrawalAudit, clock = () => new Date(), timers = globalThis } = {}) {
    this.policy = makeConsentPolicy(policy);
    if (typeof persistConsent !== "function") throw new TypeError("persistConsent callback is required");
    if (typeof clock !== "function") throw new TypeError("clock must be a function");
    if (!timers || typeof timers.setInterval !== "function" || typeof timers.clearInterval !== "function") {
      throw new TypeError("timer provider must support setInterval and clearInterval");
    }
    if (flushWithdrawalAudit !== undefined && typeof flushWithdrawalAudit !== "function") {
      throw new TypeError("flushWithdrawalAudit must be a function");
    }
    this.persistConsent = persistConsent;
    this.flushWithdrawalAudit = flushWithdrawalAudit;
    this.clock = clock;
    this.timers = timers;
    this.collectors = new Set();
    this.provider = null;
    this.captureActive = false;
    this.captureGeneration = 0;
    this.withdrawn = false;
    this.withdrawalCleanupComplete = false;
    this.auditStatus = "not_sent";
    this.auditPromise = null;
    this.researchDecisionPending = false;
    this.cameraDecisionPending = false;
    this.state = {
      research: { decision: "unknown", policy_version: policy.research.version, occurred_at: null },
      camera: {
        decision: policy.camera.offered ? "unknown" : "not_offered",
        policy_version: policy.camera.version,
        occurred_at: null,
        permission: "not_requested",
        status: "not_requested",
        modality: "non_gaze_only",
        missingness: "gaze.not_collected_by_policy",
      },
      withdrawal: { withdrawn: false, occurred_at: null, audit_status: "not_sent" },
    };
  }

  snapshot() {
    return structuredClone(this.state);
  }

  get canCollectResearch() {
    return !this.withdrawn && this.state.research.decision === "accepted";
  }

  get canCaptureCamera() {
    return this.canCollectResearch && this.state.camera.decision === "accepted" && this.state.camera.permission === "granted" && this.captureActive;
  }

  timestamp() {
    const value = this.clock();
    const date = value instanceof Date ? value : new Date(value);
    if (!Number.isFinite(date.getTime())) throw new TypeError("clock must return a valid timestamp");
    return date.toISOString();
  }

  async saveDecision(scope, decision) {
    const isResearch = scope === "research";
    if (this.withdrawn) throw new Error("Consent cannot change after withdrawal");
    if (isResearch && this.state.research.decision !== "unknown") throw new Error("Research consent was already decided");
    if (isResearch && decision === "accepted" && !this.flushWithdrawalAudit) {
      throw new Error("An approved withdrawal audit capability is required before collection can be enabled");
    }
    if (!isResearch && this.state.research.decision !== "accepted") throw new Error("Research consent must be accepted first");
    if (!isResearch && !this.policy.camera.offered) throw new Error("Camera consent is not offered by this policy");
    if (!isResearch && this.state.camera.decision !== "unknown") throw new Error("Camera consent was already decided");

    const pendingKey = isResearch ? "researchDecisionPending" : "cameraDecisionPending";
    if (this[pendingKey]) throw new Error(`${scope} consent decision is already being saved`);
    this[pendingKey] = true;
    const policyVersion = isResearch ? this.policy.research.version : this.policy.camera.version;
    const record = decisionRecord(isResearch ? "research_participation" : "camera_gaze", decision, policyVersion, this.timestamp());
    try {
      // Server persistence completes before this decision can authorize collection.
      await this.persistConsent(record);
      if (this.withdrawn) throw new Error("Consent was withdrawn while the decision was being saved");
      if (isResearch) {
        this.state.research = { decision, policy_version: policyVersion, occurred_at: record.occurred_at };
        if (decision === "declined") this.state.camera.decision = "not_offered";
      } else {
        this.state.camera = { ...this.state.camera, decision, policy_version: policyVersion, occurred_at: record.occurred_at };
      }
      return this.snapshot();
    } finally {
      this[pendingKey] = false;
    }
  }

  recordResearchConsent(decision) {
    if (!["accepted", "declined"].includes(decision)) throw new TypeError("Research consent must be accepted or declined");
    return this.saveDecision("research", decision);
  }

  recordCameraConsent(decision) {
    if (!["accepted", "declined"].includes(decision)) throw new TypeError("Camera consent must be accepted or declined");
    return this.saveDecision("camera", decision);
  }

  registerCollector(stop) {
    if (!this.canCollectResearch) throw new Error("Research consent is required before collection starts");
    if (typeof stop !== "function") throw new TypeError("collector stop callback is required");
    this.collectors.add(stop);
    return () => this.collectors.delete(stop);
  }

  registerListener(target, eventName, listener, options) {
    if (!this.canCollectResearch) throw new Error("Research consent is required before collection starts");
    if (!target || typeof target.addEventListener !== "function" || typeof target.removeEventListener !== "function") {
      throw new TypeError("listener target must support addEventListener and removeEventListener");
    }
    target.addEventListener(eventName, listener, options);
    return this.registerCollector(() => target.removeEventListener(eventName, listener, options));
  }

  registerInterval(callback, milliseconds) {
    if (typeof callback !== "function" || !Number.isFinite(milliseconds) || milliseconds < 1) {
      throw new TypeError("interval callback and positive duration are required");
    }
    if (!this.canCollectResearch) throw new Error("Research consent is required before collection starts");
    const id = this.timers.setInterval(() => {
      if (this.canCollectResearch) callback();
    }, milliseconds);
    this.collectors.add(() => this.timers.clearInterval(id));
    return id;
  }

  stopCollectors() {
    const errors = [];
    for (const stop of this.collectors) {
      try { stop(); } catch { errors.push(true); }
    }
    this.collectors.clear();
    return errors.length;
  }

  stopProvider() {
    const provider = this.provider;
    this.provider = null;
    this.captureActive = false;
    this.captureGeneration += 1;
    if (!provider || typeof provider.stop !== "function") return undefined;
    try { return provider.stop(); } catch { return undefined; }
  }

  async startCamera({ sessionId, provider, initialGeometry, onSample, onStatus = () => {}, onCameraStatus = () => {} } = {}) {
    if (!this.canCollectResearch) throw new Error("Research consent is required before camera capture");
    if (!this.policy.camera.offered || this.state.camera.decision !== "accepted") {
      throw new Error("Separate camera consent is required before camera capture");
    }
    if (!nonEmptyString(sessionId) || !provider || typeof provider.start !== "function" || typeof provider.stop !== "function" || !initialGeometry) {
      throw new TypeError("sessionId, initialGeometry, and a ProviderAdapter are required");
    }
    if (typeof onSample !== "function") throw new TypeError("onSample callback is required");
    if (this.captureActive || this.provider) throw new Error("Camera capture is already active");
    const generation = ++this.captureGeneration;
    let failureReason = null;
    this.state.camera.status = "requesting";
    onCameraStatus({ status: "requesting", modality: "non_gaze_only", recoverable: false });
    this.provider = provider;
    this.state.camera.status = "initializing";
    this.state.camera.missingness = "gaze.no_samples";

    try {
      await provider.start({
        session_id: sessionId,
        consent_granted: true,
        initial_geometry: initialGeometry,
        on_sample: (sample) => {
          if (generation === this.captureGeneration && this.canCaptureCamera) onSample(sample);
        },
        on_status: (status, reason) => {
          if (generation !== this.captureGeneration || this.withdrawn) return;
          if (status === "ready") {
            this.state.camera.permission = "granted";
            this.captureActive = true;
            this.state.camera.status = "active";
            this.state.camera.modality = "gaze_and_non_gaze";
            this.state.camera.missingness = null;
            onCameraStatus({ status: "active", modality: "gaze_and_non_gaze", recoverable: false });
          } else if (status === "unavailable") {
            failureReason = reason || "gaze.provider_failure";
            this.state.camera.permission = failureReason === "gaze.permission_denied" ? "denied" : "unavailable";
            this.state.camera.status = this.state.camera.permission === "denied" ? "denied" : "provider_failed";
            this.state.camera.modality = "non_gaze_only";
            this.state.camera.missingness = failureReason;
            this.captureActive = false;
            this.stopProvider();
            onCameraStatus({ status: this.state.camera.status, modality: "non_gaze_only", reason: failureReason, recoverable: true });
          } else if (status === "stopped" && this.captureActive) {
            this.captureActive = false;
            this.state.camera.permission = "interrupted";
            this.state.camera.status = "interrupted";
            this.state.camera.modality = "non_gaze_only";
            this.state.camera.missingness = "gaze.capture_interrupted";
            onCameraStatus({ status: "interrupted", modality: "non_gaze_only", reason: "gaze.capture_interrupted", recoverable: true });
          }
          onStatus(status, reason);
        },
      });
      if (generation !== this.captureGeneration || this.withdrawn || !this.canCollectResearch) {
        this.stopProvider();
        throw new Error("Consent was withdrawn while camera capture started");
      }
      if (this.state.camera.status === "initializing") {
        this.state.camera.permission = "granted";
        this.captureActive = true;
        this.state.camera.status = "active";
        this.state.camera.modality = "gaze_and_non_gaze";
        this.state.camera.missingness = null;
        onCameraStatus({ status: "active", modality: "gaze_and_non_gaze", recoverable: false });
      }
      return { modality: this.state.camera.modality, permission: this.state.camera.permission, status: this.state.camera.status, reason: this.state.camera.missingness };
    } catch (error) {
      if (this.withdrawn) throw error;
      if (generation !== this.captureGeneration && !failureReason) throw error;
      if (failureReason) {
        return {
          modality: "non_gaze_only",
          permission: this.state.camera.permission,
          status: this.state.camera.status,
          reason: this.state.camera.missingness,
          error,
        };
      }
      this.stopProvider();
      const failure = failureReason
        ? { permission: failureReason === "gaze.permission_denied" ? "denied" : "unavailable", status: failureReason === "gaze.permission_denied" ? "denied" : "provider_failed", reason: failureReason }
        : error?.name === "NotAllowedError" || error?.name === "SecurityError"
          ? { permission: "denied", status: "denied", reason: "gaze.permission_denied" }
          : { permission: "unavailable", status: "provider_failed", reason: "gaze.provider_failure" };
      this.state.camera.permission = failure.permission;
      this.state.camera.status = failure.status ?? "provider_failed";
      this.state.camera.modality = "non_gaze_only";
      this.state.camera.missingness = failure.reason;
      onCameraStatus({ status: this.state.camera.status, modality: "non_gaze_only", reason: failure.reason, recoverable: true });
      return { modality: "non_gaze_only", permission: failure.permission, status: this.state.camera.status, reason: failure.reason, error };
    }
  }

  async flushAuditOnly() {
    if (this.auditStatus === "sent") return "sent";
    if (!this.flushWithdrawalAudit) {
      this.auditStatus = "not_configured";
      this.state.withdrawal.audit_status = this.auditStatus;
      return this.auditStatus;
    }
    if (this.auditPromise) return this.auditPromise;
    this.auditPromise = Promise.resolve().then(() => this.flushWithdrawalAudit()).then(() => {
      this.auditStatus = "sent";
      this.state.withdrawal.audit_status = this.auditStatus;
      return this.auditStatus;
    }).catch(() => {
      this.auditStatus = "failed";
      this.state.withdrawal.audit_status = this.auditStatus;
      return this.auditStatus;
    }).finally(() => { this.auditPromise = null; });
    return this.auditPromise;
  }

  async withdraw() {
    if (!this.withdrawn) {
      this.withdrawn = true;
      this.state.research = {
        decision: "withdrawn",
        policy_version: this.policy.research.version,
        occurred_at: this.timestamp(),
      };
      this.state.withdrawal = { withdrawn: true, occurred_at: this.state.research.occurred_at, audit_status: "not_sent" };
      this.stopCollectors();
      const providerStop = this.stopProvider();
      this.withdrawalCleanupComplete = true;
      if (providerStop && typeof providerStop.then === "function") await providerStop.catch(() => {});
    }
    return { ...this.snapshot(), cleanup_complete: this.withdrawalCleanupComplete, audit_status: await this.flushAuditOnly() };
  }

  async shutdown() {
    this.withdrawn = true;
    this.stopCollectors();
    const providerStop = this.stopProvider();
    if (providerStop && typeof providerStop.then === "function") await providerStop.catch(() => {});
  }
}
