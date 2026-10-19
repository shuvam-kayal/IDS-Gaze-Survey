import type { TrialExposureEndedEvent, TrialExposureStartedEvent } from "../../../contracts/typescript/src/index.js";

export type TrialState = "ready" | "active" | "paused" | "completed" | "skipped" | "aborted";
export interface TrialTimingRules {
  /** Version copied from the server-provided timing configuration. */
  version: string;
  /** Optional maximum active exposure duration; paused time is excluded. */
  duration_ms?: number;
  /** Whether a hidden page pauses the exposure. */
  pause_on_hidden: boolean;
  /** Whether a participant or host may pause manually. */
  allow_pause?: boolean;
}
export interface TrialEventContext { experience_id: string; session_id: string; study_id: string; participant_id?: string | null }
export type TrialExposureEvent = TrialExposureStartedEvent | TrialExposureEndedEvent;
export interface TrialLifecycleOptions {
  context: TrialEventContext;
  timingRules: TrialTimingRules;
  onEvent: (event: TrialExposureEvent) => void;
  onState?: (snapshot: TrialSnapshot) => void;
  monotonicNow?: () => number;
  wallClock?: () => Date | number | string;
  eventId?: () => string;
  timers?: Pick<typeof globalThis, "setTimeout" | "clearTimeout">;
  consentController: { readonly canCollectResearch: boolean; registerCollector(stop: () => void): () => boolean; registerListener(target: EventTarget, eventName: string, listener: EventListener): () => boolean };
}
export interface TrialSnapshot { state: TrialState; trial_id: string | null; elapsed_ms: number; timing_version: string }
export class TrialLifecycle {
  constructor(options: TrialLifecycleOptions);
  readonly state: TrialState;
  readonly trialId: string | null;
  readonly timingRules: TrialTimingRules;
  elapsedMs(now?: number): number;
  snapshot(): TrialSnapshot;
  start(trialId: string): TrialSnapshot;
  pause(reason?: string): boolean;
  resume(): boolean;
  complete(): boolean;
  skip(trialId?: string): boolean;
  abort(): boolean;
  stop(): void;
  handleVisibility(hidden: boolean): boolean;
  attachLifecycle(options?: { document?: Document; window?: Window }): () => void;
}
