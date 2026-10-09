export interface Experience { id: string; name: string; origin: string; }
export interface Study { id: string; experienceId: string; status: "draft" | "active" | "paused" | "closed"; questionSetVersion: string; aoiSetVersion: string; gazeRequired: false; }
/** Camera denial never blocks participation in the current design. */
export function canParticipateWithoutCamera(study: Study): boolean { return study.gazeRequired === false; }
