export type Modality = "gaze_and_non_gaze" | "non_gaze_only";
export interface EventEnvelope { schema_version: "1.0.0"; event_id: string; experience_id: string; study_ids: string[]; session_id: string; participant_id?: string | null; event_type: string; occurred_at: string; payload: Record<string, unknown>; }
export interface CameraCapability { requested: boolean; permission: "not_requested" | "granted" | "denied" | "unavailable" | "interrupted"; }
/** Browser permission is not research consent; callers must gate capture on explicit consent separately. */
export function chooseModality(camera: CameraCapability): Modality { return camera.permission === "granted" ? "gaze_and_non_gaze" : "non_gaze_only"; }

export { fetchParticipantAoiConfigurations, fetchParticipantConfiguration, fetchSessionBootstrap, parseSessionBootstrap, parseStudyConfig, parseSurveyPlan } from "./bootstrap.js";
export { EventQueue } from "./event-queue.js";
export type { StudyConfig } from "./bootstrap.js";
export { mountParticipantEntry } from "./entry-widget.js";
export type { ParticipantEntryOptions, ParticipantEntryWidget, ParticipantInvitation } from "./entry-widget.js";
export { ConsentLifecycle } from "./consent-lifecycle.js";
export type { CameraLifecycleStatus, CameraPermission, ConsentChoice, ConsentGatedProviderAdapter, ConsentGatedProviderInput, ConsentLifecycleOptions, ConsentPolicy, ConsentRecord, ConsentState } from "./consent-lifecycle.js";
export { mountConsentFlow } from "./consent-ui.js";
export type { ConsentFlow, ConsentFlowLabels } from "./consent-ui.js";
export { TrialLifecycle } from "./trial-lifecycle.js";
export type { TrialEventContext, TrialExposureEvent, TrialLifecycleOptions, TrialSnapshot, TrialState, TrialTimingRules } from "./trial-lifecycle.js";
export { parseQuestionConfig, createSurveyRuntime, mountSurvey } from "./survey.js";
export type { QuestionAnswerType, QuestionConfig, QuestionDefinition, QuestionOption, QuestionResponse, SurveyRuntime, SurveySubmission } from "./survey.js";
export { startInteractionCapture, isSensitiveTarget } from "./interactions.js";
export type { InteractionCapture, InteractionCapturePolicy, InteractionEvent, InteractionEventType } from "./interactions.js";
export { parseAoiConfig, resolveAoiIdForTarget, createGeometryTracker } from "./geometry.js";
export type { AoiConfig, AoiDefinition, GeometryTracker, ParsedAoiConfig } from "./geometry.js";
