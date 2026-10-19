const ALLOWED = new Set(["interaction.click", "interaction.hover", "interaction.scroll", "interaction.navigation", "page.visibility_changed"]);
const EXCLUDED_TARGET = "input,textarea,select,option,form,[contenteditable],[data-sensitive]";
function idFallback() { return globalThis.crypto?.randomUUID?.() || `evt-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`; }

function isSensitiveTarget(target) {
  if (!target || typeof target.closest !== "function") return true;
  return Boolean(target.closest(EXCLUDED_TARGET));
}

/** Captures only the explicitly allowed, minimal InteractionEvent fields. */
export function startInteractionCapture({ context, policy, controller, onEvent, allowedAoiIds = [], resolveAoiId = () => null, eventId = idFallback, wallClock = () => new Date(), document: doc = globalThis.document, window: win = globalThis.window } = {}) {
  if (!context || typeof context.experience_id !== "string" || !context.experience_id.trim() || typeof context.session_id !== "string" || !context.session_id.trim() || !Array.isArray(context.study_ids) || !context.study_ids.length) {
    throw new TypeError("Interaction event context is required");
  }
  if (!policy || typeof policy.version !== "string" || !policy.version.trim() || !Array.isArray(policy.allowed_event_types) || policy.allowed_event_types.some((type) => !ALLOWED.has(type))) {
    throw new TypeError("A versioned server-provided interaction allow-list is required");
  }
  if (!controller || typeof controller.registerListener !== "function" || typeof controller.registerCollector !== "function") throw new TypeError("ConsentLifecycle controller is required");
  if (typeof onEvent !== "function" || typeof resolveAoiId !== "function" || typeof eventId !== "function") throw new TypeError("event sink and AOI resolver are required");
  if (!Array.isArray(allowedAoiIds) || allowedAoiIds.some((id) => typeof id !== "string" || !id.trim())) throw new TypeError("allowedAoiIds must contain configured AOI identifiers");
  const allowedAoiIdSet = new Set(allowedAoiIds);
  const enabled = new Set(policy.allowed_event_types);
  const uniqueStudyIds = [...new Set(context.study_ids)];
  if (uniqueStudyIds.some((id) => typeof id !== "string" || !id.trim())) throw new TypeError("study_ids must be non-empty strings");
  const cleanups = [];
  let stopped = false;
  let unregisterCapture = () => {};

  function timestamp() {
    const value = wallClock();
    const date = value instanceof Date ? value : new Date(value);
    if (!Number.isFinite(date.getTime())) throw new TypeError("wallClock must return a valid timestamp");
    return date.toISOString();
  }

  function emit(eventType, payload) {
    if (stopped || !enabled.has(eventType)) return null;
    const event = {
      schema_version: "1.0.0",
      event_id: eventId(),
      experience_id: context.experience_id,
      study_ids: uniqueStudyIds,
      session_id: context.session_id,
      ...(context.participant_id !== undefined ? { participant_id: context.participant_id } : {}),
      event_type: eventType,
      occurred_at: timestamp(),
      payload,
    };
    onEvent(event);
    return event;
  }

  function add(target, name, listener, options) {
    const unregister = controller.registerListener(target, name, listener, options);
    cleanups.push(() => {
      target.removeEventListener(name, listener, options);
      unregister();
    });
  }

  const click = (event) => {
    const target = event.target;
    if (isSensitiveTarget(target)) return;
    const payload = {};
    if (Number.isFinite(event.clientX)) payload.x_px = event.clientX;
    if (Number.isFinite(event.clientY)) payload.y_px = event.clientY;
    const aoi = resolveAoiId(target);
    if (typeof aoi === "string" && allowedAoiIdSet.has(aoi)) payload.target_aoi_id = aoi;
    emit("interaction.click", payload);
  };
  const hover = (event) => {
    const target = event.target;
    if (isSensitiveTarget(target)) return;
    const payload = {};
    const aoi = resolveAoiId(target);
    if (typeof aoi === "string" && allowedAoiIdSet.has(aoi)) payload.target_aoi_id = aoi;
    emit("interaction.hover", payload);
  };
  const scroll = () => emit("interaction.scroll", {
    scroll_x_px: Number.isFinite(win.scrollX) ? win.scrollX : 0,
    scroll_y_px: Number.isFinite(win.scrollY) ? win.scrollY : 0,
  });
  const visibility = () => emit("page.visibility_changed", { visibility_state: doc.visibilityState === "hidden" ? "hidden" : "visible" });

  try {
    if (enabled.has("interaction.click")) add(doc, "click", click, true);
    if (enabled.has("interaction.hover")) add(doc, "pointerover", hover, true);
    if (enabled.has("interaction.scroll")) add(win, "scroll", scroll, { passive: true });
    if (enabled.has("page.visibility_changed")) add(doc, "visibilitychange", visibility);
  } catch (error) {
    for (const cleanup of cleanups.splice(0)) cleanup();
    throw error;
  }

  const capture = {
    recordNavigation() { return emit("interaction.navigation", {}); },
    stop() {
      if (stopped) return;
      stopped = true;
      for (const cleanup of cleanups.splice(0)) cleanup();
      unregisterCapture?.();
    },
  };
  try {
    unregisterCapture = controller.registerCollector(() => capture.stop());
  } catch (error) {
    capture.stop();
    throw error;
  }
  return capture;
}

export { isSensitiveTarget };
