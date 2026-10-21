import { ResearcherApi, type ExperienceRecord, type ResearcherSession } from "./api.js";

function element<K extends keyof HTMLElementTagNameMap>(tag: K, text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  return node;
}

/** Mount a small accessible Experience registry; API routes remain the authorization boundary. */
export function mountExperienceRegistry(root: HTMLElement, api = new ResearcherApi()): { destroy(): void } {
  let session: ResearcherSession | null = null;
  let disposed = false;

  async function render() {
    if (disposed) return;
    root.replaceChildren();
    const main = element("section");
    main.setAttribute("aria-labelledby", "experience-registry-title");
    main.append(element("h1", "Experience registry"));
    const status = element("p"); status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite");
    const error = element("p"); error.setAttribute("role", "alert");
    main.append(status, error);
    root.append(main);

    if (!session) {
      const form = element("form");
      const title = element("h2", "Researcher sign in");
      const userLabel = element("label", "Username");
      const username = element("input"); username.name = "username"; username.autocomplete = "username"; username.required = true;
      userLabel.append(username);
      const passLabel = element("label", "Password");
      const password = element("input"); password.type = "password"; password.name = "password"; password.autocomplete = "current-password"; password.required = true;
      passLabel.append(password);
      const submit = element("button", "Sign in"); submit.type = "submit";
      form.append(title, userLabel, passLabel, submit);
      form.addEventListener("submit", async (event) => {
        event.preventDefault(); submit.disabled = true; error.textContent = "";
        try { session = await api.signIn(username.value, password.value); await render(); }
        catch (cause) { error.textContent = cause instanceof Error ? cause.message : "Sign in failed"; submit.disabled = false; }
      });
      main.append(form);
      return;
    }

    const heading = element("p", `Signed in as ${session.display_name} (${session.role})`);
    const signOut = element("button", "Sign out");
    signOut.addEventListener("click", async () => {
      signOut.disabled = true;
      try { await api.signOut(); session = null; await render(); }
      catch (cause) { error.textContent = cause instanceof Error ? cause.message : "Sign out failed"; signOut.disabled = false; }
    });
    main.append(heading, signOut);
    const permissions = new Set(session.permissions);
    if (permissions.has("experiences:manage")) {
      const form = element("form");
      form.append(element("h2", "Register an Experience"));
      const nameLabel = element("label", "Experience name");
      const name = element("input"); name.required = true; name.maxLength = 200; nameLabel.append(name);
      const originLabel = element("label", "Allowed website origins (one per line)");
      const origins = element("textarea"); origins.required = true; origins.rows = 3; origins.placeholder = "https://www.example.org"; originLabel.append(origins);
      const submit = element("button", "Create draft"); submit.type = "submit";
      form.append(nameLabel, originLabel, submit);
      form.addEventListener("submit", async (event) => {
        event.preventDefault(); submit.disabled = true; error.textContent = "";
        try {
          await api.createExperience({ name: name.value, allowed_origins: origins.value.split(/\r?\n/).map((origin) => origin.trim()).filter(Boolean) });
          name.value = ""; origins.value = ""; status.textContent = "Draft Experience created."; await render();
        } catch (cause) { error.textContent = cause instanceof Error ? cause.message : "Create failed"; submit.disabled = false; }
      });
      main.append(form);
    }
    const listHeading = element("h2", "Registered Experiences");
    const list = element("ul");
    main.append(listHeading, list);
    try {
      const experiences = await api.experiences();
      for (const record of experiences) list.append(renderExperience(record, api, session, () => render(), (message) => { error.textContent = message; }));
      if (!experiences.length) list.append(element("li", "No Experiences have been registered."));
    } catch (cause) { error.textContent = cause instanceof Error ? cause.message : "Unable to load Experiences"; }
  }

  function renderExperience(
    record: ExperienceRecord, client: ResearcherApi, activeSession: ResearcherSession,
    refresh: () => void, showError: (message: string) => void,
  ): HTMLLIElement {
    const item = element("li");
    const title = element("h3", record.name);
    const details = element("p", `${record.status} · ${record.experience_id} · ${record.allowed_origins.join(", ")}`);
    item.append(title, details);
    const allowed = new Set(activeSession.permissions);
    if (record.status === "draft" && allowed.has("experiences:manage")) {
      const edit = element("button", "Edit draft");
      edit.addEventListener("click", () => {
        const form = element("form");
        const nameLabel = element("label", "Experience name");
        const name = element("input"); name.required = true; name.maxLength = 200; name.value = record.name; nameLabel.append(name);
        const originLabel = element("label", "Allowed website origins (one per line)");
        const origins = element("textarea"); origins.required = true; origins.rows = 3; origins.value = record.allowed_origins.join("\n"); originLabel.append(origins);
        const save = element("button", "Save draft"); save.type = "submit";
        form.append(nameLabel, originLabel, save);
        form.addEventListener("submit", async (event) => {
          event.preventDefault(); save.disabled = true;
          try {
            await client.updateExperience(record.experience_id, {
              name: name.value,
              allowed_origins: origins.value.split(/\r?\n/).map((origin) => origin.trim()).filter(Boolean),
            });
            refresh();
          } catch (cause) {
            showError(cause instanceof Error ? cause.message : "Update failed");
            save.disabled = false;
          }
        });
        item.replaceChildren(title, details, form);
      });
      const publish = element("button", "Publish");
      publish.addEventListener("click", async () => {
        publish.disabled = true;
        try { await client.publishExperience(record.experience_id); refresh(); }
        catch (cause) { showError(cause instanceof Error ? cause.message : "Publish failed"); publish.disabled = false; }
      });
      item.append(edit, publish);
    }
    if (record.status !== "archived" && allowed.has("studies:archive")) {
      const archive = element("button", "Archive");
      archive.addEventListener("click", async () => {
        archive.disabled = true;
        try { await client.archiveExperience(record.experience_id); refresh(); }
        catch (cause) { showError(cause instanceof Error ? cause.message : "Archive failed"); archive.disabled = false; }
      });
      item.append(archive);
    }
    return item;
  }

  void api.session().then((result) => { session = result; return render(); }).catch(() => render());
  return { destroy() { disposed = true; root.replaceChildren(); } };
}
