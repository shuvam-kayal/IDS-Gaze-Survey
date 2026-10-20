const ENVELOPE_KEYS = new Set(["schema_version", "event_id", "experience_id", "study_ids", "session_id", "participant_id", "event_type", "occurred_at", "payload"]);
const RESPONSE_KEYS = new Set(["schema_version", "event_id", "status", "duplicate", "ingested_at"]);
const UTC_DATETIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$/;

function nonEmpty(value) { return typeof value === "string" && value.trim().length > 0; }
function validateEvent(event) {
  if (!event || typeof event !== "object" || Array.isArray(event)) throw new TypeError("EventEnvelope must be an object");
  for (const key of Object.keys(event)) if (!ENVELOPE_KEYS.has(key)) throw new TypeError(`EventEnvelope.${key} is not allowed`);
  if (event.schema_version !== "1.0.0") throw new TypeError("Unsupported EventEnvelope schema version");
  for (const key of ["event_id", "experience_id", "session_id", "event_type"]) if (!nonEmpty(event[key])) throw new TypeError(`EventEnvelope.${key} is required`);
  if (event.participant_id !== undefined && event.participant_id !== null && !nonEmpty(event.participant_id)) throw new TypeError("EventEnvelope.participant_id is invalid");
  if (!Array.isArray(event.study_ids) || new Set(event.study_ids).size !== event.study_ids.length || event.study_ids.some((id) => !nonEmpty(id))) throw new TypeError("EventEnvelope.study_ids must be unique strings");
  if (!event.payload || typeof event.payload !== "object" || Array.isArray(event.payload)) throw new TypeError("EventEnvelope.payload must be an object");
  if (typeof event.occurred_at !== "string" || !UTC_DATETIME.test(event.occurred_at) || !Number.isFinite(Date.parse(event.occurred_at))) throw new TypeError("EventEnvelope.occurred_at must be a UTC RFC 3339 date-time");
  return Object.freeze(structuredClone(event));
}
function validateReceipt(receipt, event) {
  if (!receipt || typeof receipt !== "object" || Array.isArray(receipt) || Object.keys(receipt).some((key) => !RESPONSE_KEYS.has(key)) || Object.keys(receipt).length !== RESPONSE_KEYS.size) throw new Error("Invalid event ingestion response");
  if (receipt.schema_version !== "1.0.0" || receipt.event_id !== event.event_id || !["accepted", "duplicate"].includes(receipt.status) || receipt.duplicate !== (receipt.status === "duplicate") || typeof receipt.ingested_at !== "string" || !UTC_DATETIME.test(receipt.ingested_at) || !Number.isFinite(Date.parse(receipt.ingested_at))) throw new Error("Invalid event ingestion response");
}

/** Bounded in-memory queue. Enqueue never silently drops an event; a full queue rejects the new event. */
export class EventQueue {
  constructor({ endpoint, fetchImpl = globalThis.fetch?.bind(globalThis), maxQueueSize = 1000, maxQueueBytes = 5 * 1024 * 1024, baseDelayMs = 250, maxDelayMs = 8000, maxRetriesPerFlush = 3, sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)) } = {}) {
    if (!nonEmpty(endpoint) || typeof fetchImpl !== "function") throw new TypeError("endpoint and fetchImpl are required");
    if (!Number.isInteger(maxQueueSize) || maxQueueSize < 1 || !Number.isInteger(maxQueueBytes) || maxQueueBytes < 1 || !Number.isInteger(maxRetriesPerFlush) || maxRetriesPerFlush < 0 || !Number.isFinite(baseDelayMs) || baseDelayMs < 0 || !Number.isFinite(maxDelayMs) || maxDelayMs < baseDelayMs) throw new TypeError("Invalid queue bounds or retry policy");
    this.endpoint = endpoint; this.fetchImpl = fetchImpl; this.maxQueueSize = maxQueueSize; this.maxQueueBytes = maxQueueBytes;
    this.baseDelayMs = baseDelayMs; this.maxDelayMs = maxDelayMs; this.maxRetriesPerFlush = maxRetriesPerFlush; this.sleep = sleep;
    this.events = []; this.byId = new Map(); this.bytesById = new Map(); this.queuedBytes = 0; this.flushing = null; this.detachLifecycle = null; this.abortController = null;
  }
  get size() { return this.events.length; }
  enqueue(input) {
    const event = validateEvent(input);
    const existing = this.byId.get(event.event_id);
    if (existing) {
      if (JSON.stringify(existing) !== JSON.stringify(event)) throw new Error(`event_id ${event.event_id} was reused with different content`);
      return { queued: false, duplicate: true, size: this.size };
    }
    const bytes = new TextEncoder().encode(JSON.stringify(event)).byteLength;
    if (this.size >= this.maxQueueSize || this.queuedBytes + bytes > this.maxQueueBytes) throw Object.assign(new Error("Event queue is full; event was not accepted"), { code: "EVENT_QUEUE_FULL" });
    this.events.push(event); this.byId.set(event.event_id, event); this.bytesById.set(event.event_id, bytes); this.queuedBytes += bytes;
    return { queued: true, duplicate: false, size: this.size };
  }
  async send(event, keepalive) {
    this.abortController = new AbortController();
    const response = await this.fetchImpl(this.endpoint, { method: "POST", keepalive, signal: this.abortController.signal, headers: { "Content-Type": "application/json", Accept: "application/json", "Idempotency-Key": event.event_id }, body: JSON.stringify(event) });
    if ([408, 425, 429].includes(response.status) || response.status >= 500) return { transient: true };
    if (response.status !== 200 && response.status !== 202) throw Object.assign(new Error(`Event dispatch rejected (${response.status})`), { permanent: true, status: response.status });
    const receipt = await response.json(); validateReceipt(receipt, event);
    return { accepted: true, duplicate: receipt.duplicate };
  }
  flush({ keepalive = false } = {}) {
    if (this.flushing) return this.flushing;
    this.flushing = this.flushQueue(keepalive).finally(() => { this.flushing = null; });
    return this.flushing;
  }
  async flushQueue(keepalive) {
    let attempts = 0; let delivered = 0; let lastError = null;
    while (this.events.length) {
      const event = this.events[0];
      try {
        const result = await this.send(event, keepalive);
        if (result.transient) throw Object.assign(new Error("Temporary event dispatch failure"), { transient: true });
        this.events.shift(); this.byId.delete(event.event_id); this.queuedBytes -= this.bytesById.get(event.event_id) ?? 0; this.bytesById.delete(event.event_id); delivered++; attempts = 0; lastError = null;
      } catch (error) {
        lastError = error;
        if (error.permanent) break;
        if (attempts >= this.maxRetriesPerFlush) break;
        const delay = Math.min(this.maxDelayMs, this.baseDelayMs * (2 ** attempts));
        attempts++;
        try { await this.sleep(delay); } catch { /* Keep retry bounded even if an injected delay is interrupted. */ }
      }
    }
    return { delivered, remaining: this.size, error: lastError };
  }
  attachLifecycle({ window: win = globalThis.window, document: doc = globalThis.document, consentController } = {}) {
    if (this.detachLifecycle) throw new Error("Queue lifecycle handlers are already attached");
    if (!win?.addEventListener) throw new TypeError("window event target is required");
    const online = () => { void this.flush(); };
    const pagehide = () => { void this.flush({ keepalive: true }); };
    win.addEventListener("online", online); win.addEventListener("pagehide", pagehide);
    this.detachLifecycle = () => { win.removeEventListener("online", online); win.removeEventListener("pagehide", pagehide); this.detachLifecycle = null; };
    return this.detachLifecycle;
  }
  purge() { this.abortController?.abort(); this.abortController = null; this.events.length = 0; this.byId.clear(); this.bytesById.clear(); this.queuedBytes = 0; }
  async close() { const result = await this.flush({ keepalive: true }); if (result.remaining === 0) this.detachLifecycle?.(); return result; }
}
