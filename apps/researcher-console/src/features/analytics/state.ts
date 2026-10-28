import type { ExperienceRecord, StudyRecord } from "../experiences/api.js";

export function uniqueAnalyticsStudies(
  experiences: ExperienceRecord[], studiesByExperience: Map<string, StudyRecord[]>,
): Array<{ study: StudyRecord; experience: ExperienceRecord | undefined }> {
  const seen = new Set<string>();
  const result: Array<{ study: StudyRecord; experience: ExperienceRecord | undefined }> = [];
  for (const experience of experiences) {
    for (const study of studiesByExperience.get(experience.experience_id) ?? []) {
      if (study.status === "archived" || seen.has(study.study_id)) continue;
      seen.add(study.study_id);
      result.push({ study, experience });
    }
  }
  return result.sort((left, right) => {
    const leftUpdated = left.study.updated_at || left.study.created_at || "";
    const rightUpdated = right.study.updated_at || right.study.created_at || "";
    return rightUpdated.localeCompare(leftUpdated) || left.study.study_id.localeCompare(right.study.study_id);
  });
}

export function analyticsStudyLabel(study: StudyRecord, experience?: ExperienceRecord): string {
  const shortId = study.study_id.length > 12 ? study.study_id.slice(0, 8) : study.study_id;
  return `${study.name} — ${experience?.name ?? "Experience"} [${shortId}]`;
}

export function featureVersionState(versions: string[]): { disabled: boolean; message: string } {
  return versions.length
    ? { disabled: false, message: "Feature versions loaded." }
    : { disabled: true, message: "No eligible persisted feature records are available for this Study." };
}
