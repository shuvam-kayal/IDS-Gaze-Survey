import type { ConsentLifecycle, ConsentPolicy } from "./consent-lifecycle.js";

export interface ConsentFlowLabels {
  researchTitle: string;
  acceptResearch: string;
  declineResearch: string;
  cameraTitle: string;
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
  document?: Document;
}): ConsentFlow;
