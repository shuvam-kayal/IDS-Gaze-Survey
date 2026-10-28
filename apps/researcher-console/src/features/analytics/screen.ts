import { ResearcherApi, type ExperienceRecord } from "../experiences/api.js";
import { createAnalyticsClient, type AnalysisRequestV1, type AnalysisType, type AnalysisResultV1 } from "./client.js";
import { analyticsStudyLabel, featureVersionState, uniqueAnalyticsStudies } from "./state.js";

const analysisTypes: AnalysisType[] = ["descriptive", "correlation", "group_comparison", "classification", "regression", "clustering"];

export function mountAnalyticsScreen(root: HTMLElement, api: ResearcherApi) {
  const analytics = createAnalyticsClient("http://localhost:8000/v1/analytics");
  const section = document.createElement("section");
  section.setAttribute("aria-labelledby", "analytics-title");
  const heading = document.createElement("h1"); heading.id = "analytics-title"; heading.textContent = "Study analytics";
  const intro = document.createElement("p"); intro.textContent = "Run an analysis against versioned feature data produced by the study. Results include sample scope and data limitations.";
  const status = document.createElement("p"); status.setAttribute("role", "status");
  const form = document.createElement("form");
  const studySelect = document.createElement("select"); studySelect.required = true; studySelect.setAttribute("aria-label", "Study");
  const versionSelect = document.createElement("select"); versionSelect.required = true; versionSelect.setAttribute("aria-label", "Feature set version");
  const typeSelect = document.createElement("select"); typeSelect.multiple = true; typeSelect.size = 4; typeSelect.setAttribute("aria-label", "Analysis types");
  for (const type of analysisTypes) { const option = document.createElement("option"); option.value = type; option.textContent = type.replaceAll("_", " "); if (type === "descriptive") option.selected = true; typeSelect.append(option); }
  const modality = document.createElement("select"); modality.setAttribute("aria-label", "Modality policy");
  for (const [value, label] of [["best_available", "Best available"], ["gaze_only", "Gaze only"], ["non_gaze_only", "Non-gaze only"]] as const) { const option = document.createElement("option"); option.value = value; option.textContent = label; modality.append(option); }
  const submit = document.createElement("button"); submit.type = "submit"; submit.textContent = "Run analysis";
  const results = document.createElement("div"); results.setAttribute("aria-live", "polite");
  const controls = (label: string, input: HTMLElement) => { const wrapper = document.createElement("label"); wrapper.append(document.createTextNode(label), input); return wrapper; };
  form.append(controls("Study", studySelect), controls("Feature set version", versionSelect), controls("Analysis types", typeSelect), controls("Modality", modality), submit);
  section.append(heading, intro, status, form, results); root.replaceChildren(section);

  const updateRunAvailability = () => {
    submit.disabled = !studySelect.value || !versionSelect.value || ![...typeSelect.selectedOptions].length;
  };
  updateRunAvailability();

  let versionLoad = 0;
  const loadVersions = async () => {
    const loadId = ++versionLoad;
    versionSelect.replaceChildren();
    versionSelect.disabled = true;
    updateRunAvailability();
    const studyId = studySelect.value;
    if (!studyId) return;
    status.textContent = "Loading feature versions…";
    try {
      const discovered = await analytics.listFeatureSets(studyId);
      if (loadId !== versionLoad || studySelect.value !== studyId) return;
      for (const version of discovered.feature_set_versions) { const option = document.createElement("option"); option.value = version; option.textContent = version; versionSelect.append(option); }
      const state = featureVersionState(discovered.feature_set_versions);
      versionSelect.disabled = state.disabled;
      status.textContent = state.message;
    } catch (error) {
      if (loadId !== versionLoad || studySelect.value !== studyId) return;
      versionSelect.disabled = true;
      status.textContent = error instanceof Error ? `Feature-version discovery failed: ${error.message}` : "Feature-version discovery failed.";
    }
    updateRunAvailability();
  };
  studySelect.addEventListener("change", () => { void loadVersions(); });
  typeSelect.addEventListener("change", updateRunAvailability);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const selectedTypes = [...typeSelect.selectedOptions].map((option) => option.value as AnalysisType);
    if (!selectedTypes.length || !versionSelect.value) { status.textContent = "Choose an available persisted feature version and at least one analysis type."; updateRunAvailability(); return; }
    submit.disabled = true; status.textContent = "Analysis is running…"; results.replaceChildren();
    const request: AnalysisRequestV1 = {
      schema_version: "1.0.0", analysis_request_id: crypto.randomUUID(), study_id: studySelect.value,
      feature_set_version: versionSelect.value, modality_policy: modality.value as AnalysisRequestV1["modality_policy"],
      analysis_types: selectedTypes, parameters: {}, requested_at: new Date().toISOString(),
    };
    try {
      const result: AnalysisResultV1 = await analytics.analyze(request);
      status.textContent = `Analysis ${result.status}; ${result.sample_size} records.`;
      const pre = document.createElement("pre"); pre.textContent = JSON.stringify(result, null, 2);
      const limitations = document.createElement("ul");
      for (const item of result.limitations) { const li = document.createElement("li"); li.textContent = item; limitations.append(li); }
      results.append(pre, limitations);
    } catch (error) { status.textContent = error instanceof Error ? error.message : "Analysis request failed."; }
    finally { updateRunAvailability(); }
  });

  void (async () => {
    status.textContent = "Loading studies…";
    try {
      const experiences: ExperienceRecord[] = await api.experiences();
      const studyLists = await Promise.all(experiences.map(async (experience) => [
        experience.experience_id, await api.studies(experience.experience_id),
      ] as const));
      const studies = uniqueAnalyticsStudies(experiences, new Map(studyLists));
      for (const { study, experience } of studies) {
        const option = document.createElement("option"); option.value = study.study_id;
        option.textContent = analyticsStudyLabel(study, experience);
        option.title = `Study ID: ${study.study_id}\nStatus: ${study.status}`;
        studySelect.append(option);
      }
      if (!studies.length) status.textContent = "No accessible non-archived Studies are available.";
      else { status.textContent = "Choose a study; feature versions will be discovered from persisted eligible records."; await loadVersions(); }
      updateRunAvailability();
    } catch (error) { submit.disabled = true; versionSelect.disabled = true; status.textContent = error instanceof Error ? error.message : "Could not load studies. Sign in with study viewing access."; }
  })();
  return { destroy() { root.replaceChildren(); } };
}
