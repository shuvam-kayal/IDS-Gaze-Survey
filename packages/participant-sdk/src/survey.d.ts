export type QuestionAnswerType = "single_choice" | "multi_choice" | "free_text" | "scale" | "boolean";
export interface QuestionOption { option_id: string; label: string }
export interface QuestionDefinition { question_id: string; prompt: string; answer_type: QuestionAnswerType; required: boolean; order: number; options?: QuestionOption[] }
export interface QuestionConfig { schema_version: "1.0.0"; study_id: string; question_set_version: string; questions: QuestionDefinition[] }
export interface QuestionResponse {
  response_id: string; submission_id: string; experience_id: string; session_id: string; participant_id?: string | null;
  study_id: string; question_id: string; question_set_version: string; answer_type: QuestionAnswerType; answer: string | string[] | boolean;
}
export interface SurveySubmission { submission_id: string; session_id: string; responses: QuestionResponse[] }
export interface SurveyRuntime {
  readonly questions: Array<QuestionDefinition & { study_id: string; question_set_version: string }>;
  readonly state: "editing" | "submitting" | "retryable" | "complete" | "stopped";
  readonly canCollectResearch: boolean;
  readonly submissionId: string | null;
  getPayloadForRetry(): SurveySubmission | null;
  registerCollector(stop: () => void): () => boolean;
  setAnswer(questionId: string, answer: string | string[] | boolean | null): void;
  getAnswer(questionId: string): string | string[] | boolean | undefined;
  submit(): Promise<unknown>;
  stop(): void;
}
export function parseQuestionConfig(value: unknown): QuestionConfig;
export function createSurveyRuntime(options: {
  questionConfigs: QuestionConfig[];
  surveyPlan: { schema_version: "1.0.0"; survey_plan_id: string; session_id: string; study_ids: string[]; question_ids: string[]; presentation: "end_of_session" };
  context: { experience_id: string; session_id: string; participant_id?: string | null };
  consentController: { readonly canCollectResearch: boolean; registerCollector(stop: () => void): () => boolean };
  onSubmit: (payload: SurveySubmission, options: { signal: AbortSignal }) => Promise<unknown> | unknown;
  idFactory?: () => string;
}): SurveyRuntime;
export function mountSurvey(root: Element, options: {
  runtime: SurveyRuntime;
  labels: { submit: string; retry: string; submitting: string; retrying: string; submitted: string; submitFailed: string; requiredError: string; booleanTrue: string; booleanFalse: string };
  document?: Document;
}): { form: HTMLFormElement; runtime: SurveyRuntime; destroy(): void };
