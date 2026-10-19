import type { GeometrySnapshot, ProviderAdapter, ProviderSample, ProviderStatus } from "../../../contracts/typescript/src/index.js";

export type ConsentChoice = "accepted" | "declined";
export type CameraPermission = "not_requested" | "granted" | "denied" | "unavailable" | "interrupted";
export interface ConsentPolicy {
  research: { version: string; text: string };
  camera: { version: string; text: string; offered: boolean };
}
export interface ConsentRecord {
  scope: "research_participation" | "camera_gaze";
  decision: ConsentChoice;
  policy_version: string;
  occurred_at: string;
}
export interface ConsentState {
  research: { decision: "unknown" | ConsentChoice | "withdrawn"; policy_version: string; occurred_at: string | null };
  camera: { decision: "unknown" | ConsentChoice | "not_offered"; policy_version: string; occurred_at: string | null; permission: CameraPermission };
  withdrawal: { withdrawn: boolean; occurred_at: string | null; audit_status: "not_sent" | "sent" | "failed" | "not_configured" };
}
export interface ConsentLifecycleOptions {
  policy: ConsentPolicy;
  persistConsent: (record: ConsentRecord) => Promise<void> | void;
  /** Bound by the host to the approved withdrawal audit endpoint; receives no telemetry payload. */
  flushWithdrawalAudit?: () => Promise<void> | void;
  clock?: () => Date | number | string;
  timers?: Pick<typeof globalThis, "setInterval" | "clearInterval">;
}
export class ConsentLifecycle {
  constructor(options: ConsentLifecycleOptions);
  readonly state: ConsentState;
  readonly canCollectResearch: boolean;
  readonly canCaptureCamera: boolean;
  snapshot(): ConsentState;
  recordResearchConsent(decision: ConsentChoice): Promise<ConsentState>;
  recordCameraConsent(decision: ConsentChoice): Promise<ConsentState>;
  registerCollector(stop: () => void): () => boolean;
  registerListener(target: EventTarget, eventName: string, listener: EventListenerOrEventListenerObject, options?: boolean | AddEventListenerOptions): () => boolean;
  registerInterval(callback: () => void, milliseconds: number): ReturnType<typeof setInterval>;
  startCamera(options: {
    sessionId: string;
    mediaDevices?: Pick<MediaDevices, "getUserMedia">;
    provider: ProviderAdapter;
    initialGeometry: GeometrySnapshot;
    onSample: (sample: ProviderSample) => void;
    onStatus?: (status: ProviderStatus, reason?: string) => void;
  }): Promise<{ modality: "gaze_and_non_gaze" | "non_gaze_only"; permission: CameraPermission }>;
  withdraw(): Promise<ConsentState & { cleanup_complete: boolean; audit_status: ConsentState["withdrawal"]["audit_status"] }>;
  shutdown(): Promise<void>;
}
