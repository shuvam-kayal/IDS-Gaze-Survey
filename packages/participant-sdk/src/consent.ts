export type ResearchConsent = "unknown" | "accepted" | "declined" | "withdrawn";
export type CameraPermission = "not_requested" | "granted" | "denied" | "unavailable" | "interrupted";
export interface CaptureGate { researchConsent: ResearchConsent; cameraPermission: CameraPermission; }
export function mayCaptureCamera(gate: CaptureGate): boolean { return gate.researchConsent === "accepted" && gate.cameraPermission === "granted"; }
export function modalityFor(gate: CaptureGate): "gaze_and_non_gaze" | "non_gaze_only" { return mayCaptureCamera(gate) ? "gaze_and_non_gaze" : "non_gaze_only"; }
