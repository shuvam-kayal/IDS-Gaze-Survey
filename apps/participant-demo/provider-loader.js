// Load the optional locally built P3 provider without making the non-gaze
// participant journey fail when the provider bundle has not been built.
globalThis.IDS_GAZE_PROVIDER_READY = (async () => {
  if (globalThis.IDS_GAZE_PROVIDER || new URL(globalThis.location.href).searchParams.get("mode") === "offline") return;
  try {
    const response = await fetch("/packages/gaze-provider-webgazer/smoke-test/dist/participant-webgazer.js", { cache: "no-store" });
    if (!response.ok) return;
    const source = await response.text();
    const script = document.createElement("script");
    script.textContent = source;
    document.head.append(script);
  } catch (error) {
    console.warn("Optional WebGazer provider bundle is unavailable:", error.message);
  }
})();
