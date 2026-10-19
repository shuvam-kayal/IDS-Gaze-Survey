import type { ConsentLifecycle, ConsentPolicy } from "./consent-lifecycle.js";

export interface ConsentFlowLabels {
  researchTitle: string;
  acceptResearch: string;
  declineResearch: string;
  cameraTitle: string;
  cameraReadyToStart: string;
  startCamera: string;
  cameraStarting: string;
  cameraActive: string;
  cameraDenied: string;
  cameraUnavailable: string;
  cameraUnsupported: string;
  cameraInterrupted: string;
  cameraUnplugged: string;
  cameraRevoked: string;
  providerFailed: string;
  retryCamera: string;
  continueWithoutGaze: string;
  acceptCamera: string;
  declineCamera: string;
  declinedTitle: string;
  declinedDescription: string;
  completeTitle: string;
  completeWithCameraDescription: string;
  completeWithoutCameraDescription: string;
  withdrawnDescription: string;
  withdraw: string;
  withdrawing: string;
  withdrawn: string;
  withdrawnAuditUnavailable: string;
  retryWithdrawalAudit: string;
  saving: string;
  saveFailed: string;
}
export interface ConsentFlow {
  state: string;
  destroy(): Promise<void>;
}
export function mountConsentFlow(root: Element, options: {
  controller: ConsentLifecycle;
  policy: ConsentPolicy;
  labels: ConsentFlowLabels;
  cameraOptions?: Omit<Parameters<ConsentLifecycle["startCamera"]>[0], "onCameraStatus"> & {
    onCameraStatus?: (state: { status: string; modality: "gaze_and_non_gaze" | "non_gaze_only"; reason?: string; recoverable: boolean }) => void;
  };
  onContinue?: (result: { modality: "gaze_and_non_gaze" | "non_gaze_only"; missingness: string | null }) => void | Promise<void>;
  document?: Document;
}): ConsentFlow;
