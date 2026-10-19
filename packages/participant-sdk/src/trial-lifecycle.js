function nonEmpty(value) { return typeof value === "string" && value.trim().length > 0; }
function makeId() {
  return globalThis.crypto?.randomUUID?.() || `evt-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

/** Trial exposure lifecycle. Timing policy is supplied by the pinned host config. */
export class TrialLifecycle {
  constructor({ context, timingRules, onEvent, onState = () => {}, monotonicNow = () => globalThis.performance.now(), wallClock = () => new Date(), eventId = makeId, timers = globalThis, consentController } = {}) {
    if (!context || !nonEmpty(context.experience_id) || !nonEmpty(context.session_id) || !nonEmpty(context.study_id)) {
      throw new TypeError("experience_id, session_id, and study_id are required");
    }
    if (context.participant_id !== undefined && context.participant_id !== null && !nonEmpty(context.participant_id)) {
      throw new TypeError("participant_id must be a non-empty string or null");
    }
    if (!timingRules || !nonEmpty(timingRules.version) || typeof timingRules.pause_on_hidden !== "boolean") {
      throw new TypeError("versioned timingRules with pause_on_hidden are required");
    }
    if (timingRules.allow_pause !== undefined && typeof timingRules.allow_pause !== "boolean") throw new TypeError("timingRules.allow_pause must be boolean");
    if (timingRules.duration_ms !== undefined && (!Number.isFinite(timingRules.duration_ms) || timingRules.duration_ms <= 0)) {
      throw new TypeError("timingRules.duration_ms must be positive when configured");
    }
    if (typeof onEvent !== "function" || typeof monotonicNow !== "function" || typeof wallClock !== "function" || typeof eventId !== "function") {
      throw new TypeError("event sink and clock functions are required");
    }
    if (!timers || typeof timers.setTimeout !== "function" || typeof timers.clearTimeout !== "function") {
      throw new TypeError("timer provider must support setTimeout and clearTimeout");
    }
    if (!consentController || typeof consentController.registerCollector !== "function") throw new TypeError("ConsentLifecycle controller is required");
    this.context = { ...context };
    this.timingRules = { ...timingRules };
    this.onEvent = onEvent;
    this.onState = onState;
    this.monotonicNow = monotonicNow;
    this.wallClock = wallClock;
    this.eventId = eventId;
    this.timers = timers;
    this.consentController = consentController;
    this.state = "ready";
    this.trialId = null;
    this.activeSince = null;
    this.accumulatedMs = 0;
    this.timeoutId = null;
    this.terminalEventEmitted = false;
    this.detachLifecycle = null;
    this.unregisterTrial = () => {};
  }

  elapsedMs(now = this.monotonicNow()) {
    const elapsed = this.accumulatedMs + (this.state === "active" && this.activeSince !== null ? Math.max(0, now - this.activeSince) : 0);
    return Math.max(0, elapsed);
  }

  snapshot() {
    return { state: this.state, trial_id: this.trialId, elapsed_ms: this.elapsedMs(), timing_version: this.timingRules.version };
  }

  transition(state) {
    this.state = state;
    this.onState(this.snapshot());
  }

  timestamp() {
    const value = this.wallClock();
    const date = value instanceof Date ? value : new Date(value);
    if (!Number.isFinite(date.getTime())) throw new TypeError("wallClock must return a valid timestamp");
    return date.toISOString();
  }

  emit(eventType) {
    const event = {
      schema_version: "1.0.0",
      event_id: this.eventId(),
      experience_id: this.context.experience_id,
      study_ids: [this.context.study_id],
      session_id: this.context.session_id,
      ...(this.context.participant_id !== undefined ? { participant_id: this.context.participant_id } : {}),
      event_type: eventType,
      occurred_at: this.timestamp(),
      payload: { trial_id: this.trialId },
    };
    this.onEvent(event);
    return event;
  }

  scheduleRemaining() {
    if (this.timingRules.duration_ms === undefined || this.state !== "active") return;
    const remaining = Math.max(0, this.timingRules.duration_ms - this.elapsedMs());
    this.timeoutId = this.timers.setTimeout(() => {
      this.timeoutId = null;
      if (this.state === "active" && this.elapsedMs() >= this.timingRules.duration_ms) this.complete();
      else this.scheduleRemaining();
    }, remaining);
  }

  clearTimer() {
    if (this.timeoutId !== null) this.timers.clearTimeout(this.timeoutId);
    this.timeoutId = null;
  }

  start(trialId) {
    if (this.state !== "ready") throw new Error(`Cannot start a trial from ${this.state}`);
    if (!this.consentController.canCollectResearch) throw new Error("Research consent is required before a trial can start");
    if (!nonEmpty(trialId)) throw new TypeError("trialId is required");
    this.unregisterTrial = this.consentController.registerCollector(() => this.stop());
    this.trialId = trialId;
    this.activeSince = this.monotonicNow();
    this.accumulatedMs = 0;
    this.terminalEventEmitted = false;
    this.state = "active";
    this.emit("trial.exposure_started");
    this.onState(this.snapshot());
    if (this.state === "active") this.scheduleRemaining();
    return this.snapshot();
  }

  pause(reason = "participant_or_visibility") {
    if (this.state !== "active") return false;
    if (reason === "visibility_hidden" && !this.timingRules.pause_on_hidden) return false;
    if (reason !== "visibility_hidden" && this.timingRules.allow_pause !== true) return false;
    this.accumulatedMs = this.elapsedMs();
    this.activeSince = null;
    this.clearTimer();
    this.transition("paused");
    return true;
  }

  resume() {
    if (this.state !== "paused") return false;
    this.activeSince = this.monotonicNow();
    this.transition("active");
    this.scheduleRemaining();
    return true;
  }

  terminal(state, trialId) {
    if (!["completed", "skipped", "aborted"].includes(state)) throw new TypeError("Invalid terminal trial state");
    if (["completed", "skipped", "aborted"].includes(this.state)) return false;
    if (this.state === "ready") {
      if (state === "skipped") {
        if (!nonEmpty(trialId)) throw new TypeError("trialId is required when skipping before exposure starts");
        this.trialId = trialId;
      }
      this.transition(state);
      this.detachLifecycle?.();
      return true;
    }
    this.accumulatedMs = this.elapsedMs();
    this.activeSince = null;
    this.clearTimer();
    const shouldEmitEnd = this.trialId && !this.terminalEventEmitted && (this.state === "active" || this.state === "paused");
    this.transition(state);
    if (shouldEmitEnd && this.consentController.canCollectResearch) {
      this.terminalEventEmitted = true;
      this.emit("trial.exposure_ended");
    }
    this.unregisterTrial();
    this.detachLifecycle?.();
    return true;
  }

  complete() { return this.terminal("completed"); }
  skip(trialId) { return this.terminal("skipped", trialId); }
  abort() { return this.terminal("aborted"); }

  handleVisibility(hidden) {
    if (hidden && this.timingRules.pause_on_hidden) return this.pause("visibility_hidden");
    if (!hidden && this.state === "paused") return this.resume();
    return false;
  }

  stop() {
    if (["completed", "skipped", "aborted"].includes(this.state)) return;
    this.accumulatedMs = this.elapsedMs();
    this.activeSince = null;
    this.clearTimer();
    this.terminalEventEmitted = true;
    this.transition("aborted");
    this.unregisterTrial();
    this.detachLifecycle?.();
  }

  attachLifecycle({ document: doc = globalThis.document, window: win = globalThis.window } = {}) {
    if (this.detachLifecycle) throw new Error("Trial lifecycle listeners are already attached");
    if (!doc?.addEventListener || !win?.addEventListener) throw new TypeError("document and window event targets are required");
    const add = (target, name, listener) => {
      const unregister = this.consentController
        ? this.consentController.registerListener(target, name, listener)
        : (target.addEventListener(name, listener), () => {});
      return () => { target.removeEventListener(name, listener); unregister(); };
    };
    const cleanups = [
      add(doc, "visibilitychange", () => this.handleVisibility(doc.visibilityState === "hidden")),
      add(win, "pagehide", () => this.abort()),
    ];
    this.detachLifecycle = () => {
      for (const cleanup of cleanups) cleanup();
      this.detachLifecycle = null;
    };
    return this.detachLifecycle;
  }
}
