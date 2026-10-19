function object(value) { return value !== null && typeof value === "object" && !Array.isArray(value); }
function nonEmpty(value) { return typeof value === "string" && value.trim().length > 0; }
function idFallback() { return globalThis.crypto?.randomUUID?.() || `geometry-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`; }

export function parseAoiConfig(value, { document: doc = globalThis.document } = {}) {
  if (!object(value)) throw new TypeError("AOIConfig must be an object");
  const required = ["schema_version", "experience_id", "study_id", "aoi_set_version", "aois"];
  const allowed = new Set([...required]);
  for (const key of required) if (!(key in value)) throw new TypeError(`AOIConfig.${key} is required`);
  for (const key of Object.keys(value)) if (!allowed.has(key)) throw new TypeError(`AOIConfig.${key} is not supported`);
  if (value.schema_version !== "1.0.0") throw new TypeError("Unsupported AOIConfig schema version");
  if (!nonEmpty(value.experience_id) || !nonEmpty(value.study_id) || !nonEmpty(value.aoi_set_version) || !Array.isArray(value.aois)) throw new TypeError("AOIConfig identity and AOIs are required");
  const ids = new Set();
  const aois = value.aois.map((aoi, index) => {
    if (!object(aoi)) throw new TypeError(`AOI ${index} must be an object`);
    const requiredAoi = ["aoi_id", "label", "selector", "tracking_strategy"];
    const optionalAoi = ["priority", "enabled"];
    for (const key of requiredAoi) if (!(key in aoi)) throw new TypeError(`AOI ${index}.${key} is required`);
    for (const key of Object.keys(aoi)) if (![...requiredAoi, ...optionalAoi].includes(key)) throw new TypeError(`AOI ${index}.${key} is not supported`);
    if (!nonEmpty(aoi.aoi_id) || !nonEmpty(aoi.label) || !nonEmpty(aoi.selector)) throw new TypeError(`AOI ${index} requires an ID, label, and selector`);
    if (ids.has(aoi.aoi_id)) throw new TypeError(`Duplicate AOI ID ${aoi.aoi_id}`);
    ids.add(aoi.aoi_id);
    if (!["css_selector", "data_attribute", "manual_fallback"].includes(aoi.tracking_strategy)) throw new TypeError(`AOI ${aoi.aoi_id} has an unsupported tracking strategy`);
    if (aoi.priority !== undefined && !Number.isInteger(aoi.priority)) throw new TypeError(`AOI ${aoi.aoi_id}.priority must be an integer`);
    if (aoi.enabled !== undefined && typeof aoi.enabled !== "boolean") throw new TypeError(`AOI ${aoi.aoi_id}.enabled must be boolean`);
    if (doc?.querySelector) doc.querySelector(aoi.selector);
    return { aoi_id: aoi.aoi_id, label: aoi.label, selector: aoi.selector, tracking_strategy: aoi.tracking_strategy, priority: aoi.priority ?? 0, enabled: aoi.enabled !== false };
  });
  return { schema_version: value.schema_version, experience_id: value.experience_id, study_id: value.study_id, aoi_set_version: value.aoi_set_version, aois };
}

function configsList(configs) {
  const values = Array.isArray(configs) ? configs : [configs];
  return values.flatMap((value) => {
    const config = parseAoiConfig(value);
    return config.aois.filter((aoi) => aoi.enabled).map((aoi) => ({ ...aoi, aoi_set_version: config.aoi_set_version, study_id: config.study_id }));
  });
}

/** Resolve a DOM target to the highest-priority configured AOI. */
export function resolveAoiIdForTarget(target, aoiConfigs) {
  if (!target || typeof target.closest !== "function") return null;
  const matches = [];
  for (const aoi of configsList(aoiConfigs)) {
    try { if (target.closest(aoi.selector)) matches.push(aoi); } catch { /* Invalid selectors are rejected by parseAoiConfig. */ }
  }
  matches.sort((a, b) => b.priority - a.priority || (a.aoi_id < b.aoi_id ? -1 : a.aoi_id > b.aoi_id ? 1 : 0));
  return matches[0]?.aoi_id ?? null;
}

function visibleElement(element, win) {
  if (!element?.isConnected || element.closest("[hidden]")) return false;
  let ancestor = element;
  while (ancestor && ancestor.nodeType === 1) {
    const style = win.getComputedStyle(ancestor);
    if (style.display === "none" || style.visibility === "hidden" || style.visibility === "collapse" || Number(style.opacity) === 0) return false;
    ancestor = ancestor.parentElement;
  }
  if (typeof element.checkVisibility === "function" && !element.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return false;
  return true;
}

/** Live viewport-coordinate resolver for a single study's pinned AOI set. */
export function createGeometryTracker({ aoiConfig, context, controller, onSnapshot, document: doc = globalThis.document, window: win = globalThis.window, wallClock = () => new Date(), snapshotId = idFallback, debounceMs = 40, timers = globalThis, MutationObserverImpl = globalThis.MutationObserver, ResizeObserverImpl = globalThis.ResizeObserver } = {}) {
  const config = parseAoiConfig(aoiConfig, { document: doc });
  if (!context || !nonEmpty(context.session_id) || context.experience_id !== config.experience_id || context.study_id !== config.study_id) throw new TypeError("Geometry session context must match its Experience and Study AOI config");
  if (!controller || typeof controller.registerListener !== "function" || typeof controller.registerCollector !== "function") throw new TypeError("ConsentLifecycle controller is required");
  if (typeof onSnapshot !== "function" || typeof wallClock !== "function" || typeof snapshotId !== "function") throw new TypeError("onSnapshot and clock/identity functions are required");
  if (!doc?.querySelectorAll || !win?.getComputedStyle || !timers?.setTimeout || !timers?.clearTimeout) throw new TypeError("DOM, window, and timer APIs are required");
  if (!Number.isFinite(debounceMs) || debounceMs < 0) throw new TypeError("debounceMs must be non-negative");
  const cleanups = [];
  let timerId = null;
  let stopped = false;
  let lastSnapshot = null;
  let unregisterTracker = () => {};
  const observed = new Set();
  const resizeObserver = ResizeObserverImpl ? new ResizeObserverImpl(() => schedule()) : null;

  function timestamp() {
    const value = wallClock();
    const date = value instanceof Date ? value : new Date(value);
    if (!Number.isFinite(date.getTime())) throw new TypeError("wallClock must return a valid timestamp");
    return date.toISOString();
  }

  function refreshObservedElements() {
    if (!resizeObserver) return;
    const current = new Set();
    for (const aoi of config.aois) if (aoi.enabled) {
      const element = doc.querySelector(aoi.selector);
      if (element) current.add(element);
    }
    for (const element of observed) if (!current.has(element)) resizeObserver.unobserve(element);
    for (const element of current) if (!observed.has(element)) resizeObserver.observe(element);
    observed.clear();
    for (const element of current) observed.add(element);
  }

  function buildSnapshot() {
    const viewportWidth = Number(win.innerWidth);
    const viewportHeight = Number(win.innerHeight);
    if (!(viewportWidth > 0) || !(viewportHeight > 0)) throw new Error("Viewport dimensions are unavailable");
    const rectangles = [];
    for (const aoi of config.aois) {
      if (!aoi.enabled) continue;
      let element;
      try { element = doc.querySelector(aoi.selector); } catch { continue; }
      if (!element || !visibleElement(element, win)) continue;
      const rect = element.getBoundingClientRect();
      const left = Number(rect.left);
      const top = Number(rect.top);
      const right = Number(rect.right);
      const bottom = Number(rect.bottom);
      if (![left, top, right, bottom].every(Number.isFinite) || right <= left || bottom <= top) continue;
      rectangles.push({ aoi_id: aoi.aoi_id, left_px: left, top_px: top, right_px: right, bottom_px: bottom, priority: aoi.priority });
    }
    const visualScale = Number(win.visualViewport?.scale);
    return {
      schema_version: "2.0.0",
      snapshot_id: snapshotId(),
      session_id: context.session_id,
      study_id: context.study_id,
      captured_at: timestamp(),
      aoi_set_version: config.aoi_set_version,
      viewport_width_px: viewportWidth,
      viewport_height_px: viewportHeight,
      scroll_x_px: Math.max(0, Number(win.scrollX) || 0),
      scroll_y_px: Math.max(0, Number(win.scrollY) || 0),
      zoom: Number.isFinite(visualScale) && visualScale > 0 ? visualScale : 1,
      rectangles,
    };
  }

  function geometryKey(snapshot) {
    const { snapshot_id: _snapshotId, captured_at: _capturedAt, ...geometry } = snapshot;
    return JSON.stringify(geometry);
  }

  function collect() {
    if (stopped) return lastSnapshot;
    refreshObservedElements();
    const next = buildSnapshot();
    if (!lastSnapshot || geometryKey(lastSnapshot) !== geometryKey(next)) {
      lastSnapshot = next;
      onSnapshot(next);
    }
    return lastSnapshot;
  }

  function flush() {
    if (timerId !== null) timers.clearTimeout(timerId);
    timerId = null;
    return collect();
  }

  function schedule() {
    if (stopped) return;
    if (timerId !== null) timers.clearTimeout(timerId);
    timerId = timers.setTimeout(() => { timerId = null; collect(); }, debounceMs);
  }

  function add(target, name, listener, options) {
    const unregister = controller.registerListener(target, name, listener, options);
    cleanups.push(() => { target.removeEventListener(name, listener, options); unregister(); });
  }

  const mutationObserver = MutationObserverImpl && doc.documentElement ? new MutationObserverImpl(() => schedule()) : null;
  const stop = () => {
    if (stopped) return;
    stopped = true;
    if (timerId !== null) timers.clearTimeout(timerId);
    timerId = null;
    mutationObserver?.disconnect();
    resizeObserver?.disconnect();
    for (const cleanup of cleanups.splice(0)) cleanup();
    unregisterTracker();
  };
  const tracker = {
    start() {
      if (stopped) throw new Error("Geometry tracker has stopped");
      if (lastSnapshot) return lastSnapshot;
      try {
        add(win, "resize", schedule);
        add(win, "scroll", schedule, { passive: true });
        add(doc, "scroll", schedule, true);
        if (win.visualViewport) {
          add(win.visualViewport, "resize", schedule);
          add(win.visualViewport, "scroll", schedule, { passive: true });
        }
        mutationObserver?.observe(doc.documentElement, { attributes: true, childList: true, characterData: true, subtree: true });
        unregisterTracker = controller.registerCollector(stop);
        return collect();
      } catch (error) {
        stop();
        throw error;
      }
    },
    flush,
    stop,
    resolveTarget(target) { return resolveAoiIdForTarget(target, config); },
    get latest() { return lastSnapshot; },
  };
  return tracker;
}
