import type { ConsolidatedSurveyPlan, SessionBootstrap } from "../../../contracts/typescript/src/index.js";

export type SessionBootstrapPayload = Omit<SessionBootstrap, "participant_id"> & { participant_id?: string | null };

export interface StudyConfig {
  schema_version: "1.0.0";
  study_id: string;
  experience_id: string;
  config_version: string;
  status: "draft" | "active" | "paused" | "closed";
  aoi_set_version: string;
  question_set_version: string;
  survey_policy: {
    timing: "before_exposure" | "after_exposure" | "after_each_trial" | "batched_after_exposure";
    consolidation: "deduplicate_by_question_id" | "keep_study_scoped";
  };
  gaze_required: false;
  priority?: number;
}

export function parseSessionBootstrap(value: unknown, options?: { now?: number }): SessionBootstrapPayload;
export function parseStudyConfig(value: unknown, options?: { bootstrap?: SessionBootstrapPayload; study?: SessionBootstrap["eligible_studies"][number] }): StudyConfig;
export function parseSurveyPlan(value: unknown, options?: { bootstrap?: SessionBootstrapPayload }): ConsolidatedSurveyPlan;
export function fetchSessionBootstrap(options: {
  endpoint: string;
  experienceId: string;
  fetchImpl?: typeof fetch;
  now?: number;
}): Promise<SessionBootstrapPayload>;
export function fetchParticipantConfiguration(options: {
  bootstrapUrl: string;
  experienceId: string;
  studyConfigUrl: (studyId: string, configVersion: string) => string;
  surveyPlanUrl: (sessionId: string) => string;
  fetchImpl?: typeof fetch;
  now?: number;
}): Promise<{
  bootstrap: SessionBootstrapPayload;
  studyConfigs: StudyConfig[];
  surveyPlan: ConsolidatedSurveyPlan;
  modalityOptions: { camera_capture_supported: boolean; gaze_required: boolean; non_gaze_available: true };
}>;
