import { ResearcherApi, type ResearcherSession, type StudyInput, type StudyRecord } from "../experiences/api.js";

function el<K extends keyof HTMLElementTagNameMap>(tag: K, text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  return node;
}

/** Accessible JSON-backed study authoring; the API remains the authorization boundary. */
export function mountStudyAuthoring(root: HTMLElement, api = new ResearcherApi()): { destroy(): void } {
  let disposed = false;
  const render = async () => {
    if (disposed) return;
    root.replaceChildren();
    const main = el("main");
    main.append(el("h1", "Study configuration"));
    const status = el("p"); status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite");
    const error = el("p"); error.setAttribute("role", "alert"); main.append(status, error);
    let session: ResearcherSession;
    try { session = await api.session(); }
    catch { main.append(el("p", "Sign in through the Experience registry before editing studies.")); root.append(main); return; }
    if (!session.permissions.includes("studies:create") && !session.permissions.includes("studies:edit")) {
      main.append(el("p", "Your account can view studies but cannot edit them.")); root.append(main); return;
    }
    main.append(el("p", `Signed in as ${session.display_name} (${session.role})`));
    const form = el("form"); form.append(el("h2", "Create or edit a draft Study"));
    const fields = new Map<string, HTMLInputElement | HTMLTextAreaElement>();
    const addInput = (key: string, labelText: string, initial: string, multiline = false) => {
      const label = el("label", labelText);
      const input = multiline ? el("textarea") : el("input");
      input.name = key; input.value = initial; if (multiline) (input as HTMLTextAreaElement).rows = 5;
      label.append(input); fields.set(key, input); form.append(label);
    };
    const fieldValue = (key: string): string => {
      const field = fields.get(key);
      if (!field) throw new Error(`Missing ${key} field.`);
      return field.value;
    };
    addInput("study_id", "Draft Study ID to edit (leave blank to create)", "");
    addInput("experience_id", "Published Experience ID", "");
    addInput("name", "Study name", "");
    addInput("priority", "Assignment priority (higher runs first)", "0");
    addInput("eligibility_rules", "Eligibility rules (JSON)", '{"all": []}', true);
    addInput("timing_rules", "Timing rules (JSON)", "{}", true);
    addInput("survey_policy", "Survey timing and consolidation policy (JSON)", '{"timing":"after_exposure","consolidation":"deduplicate_by_question_id"}', true);
    addInput("aois", "AOI definitions (JSON array)", "[]", true);
    addInput("questions", "Question definitions (JSON array)", "[]", true);
    const save = el("button", "Save draft"); save.type = "submit"; form.append(save);
    form.addEventListener("submit", async (event) => {
      event.preventDefault(); save.disabled = true; error.textContent = "";
      try {
        const parse = (key: string) => {
          return JSON.parse(fieldValue(key));
        };
        const input: StudyInput = { experience_id: fieldValue("experience_id").trim(), name: fieldValue("name").trim(),
          priority: Number(fieldValue("priority")), eligibility_rules: parse("eligibility_rules"),
          timing_rules: parse("timing_rules"), survey_policy: parse("survey_policy"),
          aois: parse("aois"), questions: parse("questions") };
        if (!Number.isInteger(input.priority)) throw new Error("Priority must be a whole number.");
        const id = fieldValue("study_id").trim();
        await (id ? api.updateStudy(id, input) : api.createStudy(input.experience_id, input));
        status.textContent = "Draft Study saved."; await showStudies(input.experience_id);
      } catch (cause) { error.textContent = cause instanceof Error ? cause.message : "Unable to save draft"; }
      finally { save.disabled = false; }
    });
    main.append(form);
    const results = el("section"); results.setAttribute("aria-labelledby", "study-list-title");
    const listTitle = el("h2", "Studies for an Experience"); listTitle.id = "study-list-title";
    results.append(listTitle);
    const loadForm = el("form");
    const loadLabel = el("label", "Experience ID"); const expInput = el("input"); expInput.required = true; loadLabel.append(expInput);
    const load = el("button", "Load studies"); load.type = "submit"; loadForm.append(loadLabel, load);
    loadForm.addEventListener("submit", (event) => { event.preventDefault(); void showStudies(expInput.value.trim()); });
    results.append(loadForm); main.append(results); root.append(main);

    async function showStudies(experienceId: string) {
      try {
        const list = el("ul");
        const records = await api.studies(experienceId);
        for (const study of records) list.append(renderStudy(study));
        if (!records.length) list.append(el("li", "No Studies configured."));
        results.querySelector("ul")?.remove(); results.append(list);
      } catch (cause) { error.textContent = cause instanceof Error ? cause.message : "Unable to load Studies"; }
    }
    function renderStudy(study: StudyRecord): HTMLLIElement {
      const item = el("li", `${study.name} · ${study.status} · priority ${study.priority}${study.config_version ? ` · ${study.config_version}` : ""}`);
      if (study.status === "draft" && session.permissions.includes("studies:edit")) {
        const edit = el("button", "Edit draft");
        edit.addEventListener("click", () => {
          fields.get("study_id")!.value = study.study_id;
          fields.get("experience_id")!.value = study.experience_id;
          fields.get("name")!.value = study.name;
          fields.get("priority")!.value = String(study.priority);
          fields.get("eligibility_rules")!.value = JSON.stringify(study.eligibility_rules, null, 2);
          fields.get("timing_rules")!.value = JSON.stringify(study.config.timing_rules ?? {}, null, 2);
          fields.get("survey_policy")!.value = JSON.stringify(study.config.survey_policy ?? { timing: "after_exposure", consolidation: "deduplicate_by_question_id" }, null, 2);
          fields.get("aois")!.value = JSON.stringify(study.config.aois ?? [], null, 2);
          fields.get("questions")!.value = JSON.stringify(study.config.questions ?? [], null, 2);
          fields.get("name")!.focus();
        });
        item.append(edit);
      }
      if (study.status === "draft" && session.permissions.includes("studies:publish")) {
        const publish = el("button", "Publish immutable config");
        publish.addEventListener("click", async () => { try { await api.publishStudy(study.study_id); await showStudies(study.experience_id); } catch (cause) { error.textContent = cause instanceof Error ? cause.message : "Publish failed"; } }); item.append(publish);
      }
      if (study.status !== "archived" && session.permissions.includes("studies:archive")) {
        const archive = el("button", "Archive");
        archive.addEventListener("click", async () => { try { await api.archiveStudy(study.study_id); await showStudies(study.experience_id); } catch (cause) { error.textContent = cause instanceof Error ? cause.message : "Archive failed"; } }); item.append(archive);
      }
      return item;
    }
  };
  void render();
  return { destroy() { disposed = true; root.replaceChildren(); } };
}
