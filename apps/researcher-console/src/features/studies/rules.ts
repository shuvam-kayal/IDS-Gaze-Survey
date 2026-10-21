export type EligibilityRule = { all: EligibilityRule[] } | { any: EligibilityRule[] } | { not: EligibilityRule }
  | { field: string; op: "eq" | "ne" | "in" | "contains" | "gte" | "lte" | "exists"; value?: unknown };
export interface StudyConfig {
  study_id: string; experience_id: string; status: "draft" | "published" | "archived";
  priority: number; eligibility_rules: EligibilityRule; config_version: string | null;
}

/** Bounded counterpart of the server's data-only eligibility DSL. */
export function matchesEligibility(rule: EligibilityRule, attributes: Record<string, unknown>): boolean {
  if ("all" in rule) return rule.all.every((child) => matchesEligibility(child, attributes));
  if ("any" in rule) return rule.any.some((child) => matchesEligibility(child, attributes));
  if ("not" in rule) return !matchesEligibility(rule.not, attributes);
  const actual = attributes[rule.field];
  switch (rule.op) {
    case "exists": return (rule.field in attributes) === Boolean(rule.value);
    case "eq": return actual === rule.value;
    case "ne": return actual !== rule.value;
    case "in": return Array.isArray(rule.value) && rule.value.includes(actual);
    case "contains": return typeof actual === "string" ? actual.includes(String(rule.value)) : Array.isArray(actual) && actual.includes(rule.value);
    case "gte": return typeof actual === "number" && typeof rule.value === "number" && actual >= rule.value;
    case "lte": return typeof actual === "number" && typeof rule.value === "number" && actual <= rule.value;
  }
}

export function eligibleStudies(studies: StudyConfig[], attributes: Record<string, unknown>): StudyConfig[] {
  return studies.filter((study) => study.status === "published" && matchesEligibility(study.eligibility_rules, attributes))
    .sort((a, b) => b.priority - a.priority || a.study_id.localeCompare(b.study_id));
}

export function selectStudies(studies: StudyConfig[], attributes: Record<string, unknown>, strategy: "eligible_all" | "prioritized"): StudyConfig[] {
  const eligible = eligibleStudies(studies, attributes);
  return strategy === "prioritized" ? eligible.slice(0, 1) : eligible;
}
