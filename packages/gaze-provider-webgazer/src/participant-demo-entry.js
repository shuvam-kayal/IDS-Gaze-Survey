import { createWebGazerAdapter } from "./webgazer-adapter.js";

let activeAdapter = null;

// P1 supplies this narrow ProviderAdapter boundary after consent. The
// adapter remains the only code that talks to WebGazer or owns its camera.
const provider = {
  async start(input) {
    if (activeAdapter) throw new Error("WebGazer provider is already active");
    const adapter = await createWebGazerAdapter({
      viewport: () => ({ width: globalThis.innerWidth, height: globalThis.innerHeight }),
    });
    try {
      await adapter.start(input);
      activeAdapter = adapter;
    } catch (error) {
      adapter.stop();
      throw error;
    }
  },
  stop(reason = "gaze.capture_interrupted") {
    const adapter = activeAdapter;
    activeAdapter = null;
    adapter?.stop(reason);
  },
};

// Preserve an explicitly injected test provider. This keeps the participant
// SDK harness deterministic while production/local runs use WebGazer.
if (!globalThis.IDS_GAZE_PROVIDER) globalThis.IDS_GAZE_PROVIDER = provider;
