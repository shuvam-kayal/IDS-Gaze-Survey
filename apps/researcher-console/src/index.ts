export { ResearcherApi } from "./features/experiences/api.js";
export type { ExperienceRecord, ExperienceStatus, ResearcherRole, ResearcherSession } from "./features/experiences/api.js";
export { mountExperienceRegistry } from "./features/experiences/screen.js";
export { mountStudyAuthoring } from "./features/studies/screen.js";
export { eligibleStudies, matchesEligibility, selectStudies } from "./features/studies/rules.js";
export type { StudyConfig, EligibilityRule } from "./features/studies/rules.js";
export type { StudyRecord, StudyInput } from "./features/experiences/api.js";
