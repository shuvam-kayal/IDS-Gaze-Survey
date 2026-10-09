export type Modality = "gaze_and_non_gaze" | "non_gaze_only";
export interface EventEnvelope { schema_version: "1.0.0"; event_id: string; experience_id: string; study_ids: string[]; session_id: string; participant_id?: string; event_type: string; occurred_at: string; payload: Record<string, unknown>; }
export interface CameraCapability { requested: boolean; permission: "not_requested" | "granted" | "denied" | "unavailable" | "interrupted"; }
/** Browser permission is not research consent; callers must gate capture on explicit consent separately. */
export function chooseModality(camera: CameraCapability): Modality { return camera.permission === "granted" ? "gaze_and_non_gaze" : "non_gaze_only"; }
