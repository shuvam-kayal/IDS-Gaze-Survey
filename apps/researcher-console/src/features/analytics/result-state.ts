export type ResultState = "queued"|"running"|"succeeded"|"failed"|"insufficient_data";
export interface ResultSummary { analysisId:string; studyId:string; modality:"gaze_and_non_gaze"|"non_gaze_only"; status:ResultState; sampleSize:number; limitations:string[]; }
export function canShowInterpretation(result:ResultSummary):boolean { return result.status==="succeeded" && result.sampleSize>0; }
