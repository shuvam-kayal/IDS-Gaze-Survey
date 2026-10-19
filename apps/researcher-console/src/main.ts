import "./style.css";
import { mountExperienceRegistry } from "./features/experiences/screen.js";
import { mountStudyAuthoring } from "./features/studies/screen.js";
import { ResearcherApi } from "./features/experiences/api.js";

const app = document.querySelector<HTMLElement>("#app");
if (!app) throw new Error("Researcher console root is missing");
const api = new ResearcherApi();
let destroyCurrent = () => {};

function show(view: "experiences" | "studies" | "analytics") {
  destroyCurrent();
  for (const button of document.querySelectorAll<HTMLButtonElement>("[data-view]")) {
    const selected = button.dataset.view === view;
    button.setAttribute("aria-current", selected ? "page" : "false");
  }
  const panel = document.querySelector<HTMLElement>("#view-root");
  if (!panel) return;
  panel.replaceChildren();
  panel.setAttribute("aria-busy", "true");
  const status = document.createElement("p");
  status.className = "loading"; status.setAttribute("role", "status"); status.textContent = "Loading…";
  panel.append(status);
  panel.setAttribute("aria-busy", "false");
  if (view === "experiences") destroyCurrent = mountExperienceRegistry(panel, api).destroy;
  else if (view === "studies") destroyCurrent = mountStudyAuthoring(panel, api).destroy;
  else {
    const section = document.createElement("section");
    section.setAttribute("aria-labelledby", "analytics-title");
    const heading = document.createElement("h1"); heading.id = "analytics-title"; heading.textContent = "Study analytics";
    const note = document.createElement("p"); note.textContent = "Analysis requests and result interpretation are provided by the P4 analytics module. This console exposes the result-state integration point and does not calculate or reinterpret study results.";
    const contract = document.createElement("code"); contract.textContent = "ResultState · ResultSummary · canShowInterpretation";
    section.append(heading, note, contract); panel.replaceChildren(section);
  }
}

app.replaceChildren();
app.setAttribute("aria-busy", "false");
const shell = document.createElement("div"); shell.className = "console-shell";
const sidebar = document.createElement("aside"); sidebar.className = "sidebar";
const brand = document.createElement("a"); brand.href = "#experiences"; brand.className = "brand";
brand.textContent = "IDS · Research";
const navigation = document.createElement("nav"); navigation.setAttribute("aria-label", "Researcher console");
const navItems: Array<["experiences" | "studies" | "analytics", string]> = [
  ["experiences", "Experiences"], ["studies", "Studies"], ["analytics", "Analytics"],
];
for (const [view, label] of navItems) {
  const button = document.createElement("button"); button.type = "button"; button.dataset.view = view;
  button.textContent = label; button.addEventListener("click", () => show(view)); navigation.append(button);
}
const sidebarFoot = document.createElement("p"); sidebarFoot.textContent = "Research configuration and session-safe publishing";
sidebar.append(brand, navigation, sidebarFoot);
const content = document.createElement("div"); content.className = "content";
const topbar = document.createElement("header"); topbar.className = "topbar";
const breadcrumb = document.createElement("p"); breadcrumb.textContent = "Research workspace";
const topStatus = document.createElement("span"); topStatus.setAttribute("role", "status"); topStatus.textContent = "Connected to control plane";
const seedButton = document.createElement("button"); seedButton.type = "button"; seedButton.textContent = "Create E2E seed workspace";
seedButton.addEventListener("click", async () => {
  seedButton.disabled = true; topStatus.textContent = "Creating demo Experience and Studies…";
  try {
    const fixture = await (await fetch("/seed-fixtures.json")).json();
    const experience = await api.createExperience(fixture.experience);
    await api.publishExperience(experience.experience_id);
    for (const seed of fixture.studies) {
      const study = await api.createStudy(experience.experience_id, { ...seed, experience_id: experience.experience_id });
      await api.publishStudy(study.study_id);
    }
    topStatus.textContent = `Seeded ${experience.name} (${experience.experience_id}) with ${fixture.studies.length} Studies.`;
    show("experiences");
  } catch (cause) {
    topStatus.textContent = cause instanceof Error ? `Seed failed: ${cause.message}` : "Seed failed.";
  } finally { seedButton.disabled = false; }
});
topbar.append(breadcrumb, seedButton, topStatus);
const viewRoot = document.createElement("div"); viewRoot.id = "view-root"; viewRoot.className = "view-root";
content.append(topbar, viewRoot); shell.append(sidebar, content); app.append(shell);
show("experiences");
