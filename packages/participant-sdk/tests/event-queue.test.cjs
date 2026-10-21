const test = require("node:test");
const assert = require("node:assert/strict");
const { EventQueue } = require("../src/event-queue.js");

function event(id) {
  return { schema_version: "1.0.0", event_id: id, experience_id: "exp-demo", study_ids: ["study-demo"], session_id: "session-demo", event_type: "trial.exposure_started", occurred_at: "2026-10-19T10:00:00.000Z", payload: { trial_id: "trial-1" } };
}
function receipt(id, duplicate = false) {
  return { schema_version: "1.0.0", event_id: id, status: duplicate ? "duplicate" : "accepted", duplicate, ingested_at: "2026-10-19T10:00:01.000Z" };
}
function response(status, body) { return { status, json: async () => body }; }

test("offline retry retains the event, uses stable idempotency, and deduplicates an accepted request whose response was lost", async () => {
  const stored = new Map(); const keys = []; const delays = []; let calls = 0; let online = false; let dropResponse = true;
  const queue = new EventQueue({ endpoint: "/v1/events", maxRetriesPerFlush: 2, baseDelayMs: 7, sleep: async (ms) => delays.push(ms), fetchImpl: async (_url, init) => {
    calls++; keys.push(init.headers["Idempotency-Key"]);
    if (!online) return response(503, {});
    const body = JSON.parse(init.body);
    if (stored.has(body.event_id)) return response(200, receipt(body.event_id, true));
    stored.set(body.event_id, body);
    if (dropResponse) { dropResponse = false; throw new TypeError("connection dropped after server commit"); }
    return response(202, receipt(body.event_id));
  } });
  queue.enqueue(event("evt-stable"));
  const offline = await queue.flush();
  assert.equal(offline.remaining, 1);
  assert.equal(queue.size, 1);
  online = true;
  const recovered = await queue.flush();
  assert.equal(recovered.delivered, 1);
  assert.equal(recovered.remaining, 0);
  assert.deepEqual(keys, ["evt-stable", "evt-stable", "evt-stable", "evt-stable", "evt-stable"]);
  assert.equal(stored.size, 1);
  assert.deepEqual(delays, [7, 14, 7]);
});

test("queue is bounded, duplicate enqueues are idempotent, and event ID conflicts are rejected", () => {
  const queue = new EventQueue({ endpoint: "/events", maxQueueSize: 1, fetchImpl: async () => response(202, receipt("x")) });
  assert.deepEqual(queue.enqueue(event("x")), { queued: true, duplicate: false, size: 1 });
  assert.deepEqual(queue.enqueue(event("x")), { queued: false, duplicate: true, size: 1 });
  assert.throws(() => queue.enqueue(event("y")), { code: "EVENT_QUEUE_FULL" });
  assert.throws(() => queue.enqueue({ ...event("x"), payload: { changed: true } }), /reused with different content/);
  const byteBound = new EventQueue({ endpoint: "/events", maxQueueBytes: 1, fetchImpl: async () => response(202, receipt("large")) });
  assert.throws(() => byteBound.enqueue(event("large")), { code: "EVENT_QUEUE_FULL" });
  assert.equal(byteBound.size, 0);
});

test("permanent server rejection is visible and leaves the event queued", async () => {
  const queue = new EventQueue({ endpoint: "/events", fetchImpl: async () => response(422, {}) });
  queue.enqueue(event("bad"));
  const result = await queue.flush();
  assert.equal(result.remaining, 1);
  assert.equal(result.error.status, 422);
});

test("withdrawal purge aborts dispatch and clears queued research events without flushing them", async () => {
  let signal; let requests = 0;
  const queue = new EventQueue({ endpoint: "/events", fetchImpl: (_url, init) => {
    requests++; signal = init.signal;
    return new Promise((_resolve, reject) => init.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true }));
  } });
  queue.enqueue(event("pending"));
  const flushing = queue.flush();
  await Promise.resolve();
  queue.purge();
  const result = await flushing;
  assert.equal(signal.aborted, true);
  assert.equal(queue.size, 0);
  assert.equal(requests, 1);
  assert.equal(result.remaining, 0);
});
