import type { GeometrySnapshot, ProviderSample, ProviderStatus } from "../../../contracts/typescript/src/index.js";

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
export type CameraLifecycleStatus = "not_requested" | "requesting" | "initializing" | "active" | "denied" | "unavailable" | "unsupported" | "interrupted" | "unplugged" | "revoked" | "provider_failed";
export interface ConsentState {
  research: { decision: "unknown" | ConsentChoice | "withdrawn"; policy_version: string; occurred_at: string | null };
  camera: { decision: "unknown" | ConsentChoice | "not_offered"; policy_version: string; occurred_at: string | null; permission: CameraPermission; status: CameraLifecycleStatus; modality: "gaze_and_non_gaze" | "non_gaze_only"; missingness: string | null };
  withdrawal: { withdrawn: boolean; occurred_at: string | null; audit_status: "not_sent" | "sent" | "failed" | "not_configured" };
}
/** Revocable access to a consented video track. The MediaStream remains owned by P1. */
export interface ConsentGatedCameraSource {
  getVideoTrack(): MediaStreamTrack | null;
  isActive(): boolean;
}
export interface ConsentGatedProviderInput {
  session_id: string;
  camera_source: ConsentGatedCameraSource;
  initial_geometry: GeometrySnapshot;
  on_sample: (sample: ProviderSample) => void;
  on_status: (status: ProviderStatus, reason?: string) => void;
}
/** P3 adapter implementation behind the consent-gated SDK bridge. */
export interface ConsentGatedProviderAdapter {
  start(input: ConsentGatedProviderInput): Promise<void>;
  stop(): void;
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
    provider: ConsentGatedProviderAdapter;
    initialGeometry: GeometrySnapshot;
    onSample: (sample: ProviderSample) => void;
    onStatus?: (status: ProviderStatus, reason?: string) => void;
    onCameraStatus?: (state: { status: CameraLifecycleStatus; modality: "gaze_and_non_gaze" | "non_gaze_only"; reason?: string; recoverable: boolean }) => void;
    permissions?: Pick<Permissions, "query">;
  }): Promise<{ modality: "gaze_and_non_gaze" | "non_gaze_only"; permission: CameraPermission; status: CameraLifecycleStatus; reason: string | null; error?: unknown; recoverable?: boolean }>;
  withdraw(): Promise<ConsentState & { cleanup_complete: boolean; audit_status: ConsentState["withdrawal"]["audit_status"] }>;
  shutdown(): Promise<void>;
}
