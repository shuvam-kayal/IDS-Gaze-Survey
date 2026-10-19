export type Modality = "gaze_and_non_gaze" | "non_gaze_only";
export interface EventEnvelope { schema_version: "1.0.0"; event_id: string; experience_id: string; study_ids: string[]; session_id: string; participant_id?: string | null; event_type: string; occurred_at: string; payload: Record<string, unknown>; }
export interface CameraCapability { requested: boolean; permission: "not_requested" | "granted" | "denied" | "unavailable" | "interrupted"; }
/** Browser permission is not research consent; callers must gate capture on explicit consent separately. */
export function chooseModality(camera: CameraCapability): Modality { return camera.permission === "granted" ? "gaze_and_non_gaze" : "non_gaze_only"; }

export { fetchParticipantConfiguration, fetchSessionBootstrap, parseSessionBootstrap, parseStudyConfig, parseSurveyPlan } from "./bootstrap.js";
export type { StudyConfig } from "./bootstrap.js";
export { mountParticipantEntry } from "./entry-widget.js";
export type { ParticipantEntryOptions, ParticipantEntryWidget, ParticipantInvitation } from "./entry-widget.js";
export { ConsentLifecycle } from "./consent-lifecycle.js";
export type { CameraPermission, ConsentChoice, ConsentLifecycleOptions, ConsentPolicy, ConsentRecord, ConsentState } from "./consent-lifecycle.js";
export { mountConsentFlow } from "./consent-ui.js";
export type { ConsentFlow, ConsentFlowLabels } from "./consent-ui.js";
