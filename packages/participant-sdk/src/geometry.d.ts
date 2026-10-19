import type { GeometrySnapshotV2 } from "../../../contracts/typescript/src/index.js";

export interface AoiDefinition { aoi_id: string; label: string; selector: string; tracking_strategy: "css_selector" | "data_attribute" | "manual_fallback"; priority?: number; enabled?: boolean }
export interface AoiConfig { schema_version: "1.0.0"; experience_id: string; study_id: string; aoi_set_version: string; aois: AoiDefinition[] }
export interface ParsedAoiConfig extends AoiConfig { aois: Array<AoiDefinition & { priority: number; enabled: boolean }> }
export interface GeometryTracker {
  start(): GeometrySnapshotV2;
  flush(): GeometrySnapshotV2 | null;
  stop(): void;
  resolveTarget(target: Element): string | null;
  readonly latest: GeometrySnapshotV2 | null;
}
export function parseAoiConfig(value: unknown, options?: { document?: Document }): ParsedAoiConfig;
export function resolveAoiIdForTarget(target: Element, aoiConfigs: AoiConfig | AoiConfig[] | ParsedAoiConfig | ParsedAoiConfig[]): string | null;
export function createGeometryTracker(options: {
  aoiConfig: AoiConfig;
  context: { experience_id: string; study_id: string; session_id: string };
  controller: { registerListener(target: EventTarget, eventName: string, listener: EventListener, options?: boolean | AddEventListenerOptions): () => boolean; registerCollector(stop: () => void): () => boolean };
  onSnapshot: (snapshot: GeometrySnapshotV2) => void;
  document?: Document;
  window?: Window;
  wallClock?: () => Date | number | string;
  snapshotId?: () => string;
  debounceMs?: number;
  timers?: Pick<typeof globalThis, "setTimeout" | "clearTimeout">;
  MutationObserverImpl?: typeof MutationObserver;
  ResizeObserverImpl?: typeof ResizeObserver;
}): GeometryTracker;
