const STYLE_ID = "ids-participant-entry-styles";
let widgetSequence = 0;

const styles = `
  .ids-entry-launcher { font: inherit; cursor: pointer; }
  .ids-entry-dialog { box-sizing: border-box; width: min(32rem, calc(100vw - 2rem)); max-height: min(85vh, 42rem); overflow: auto; border: 0; border-radius: .75rem; padding: 1.5rem; color: #17202a; background: #fff; box-shadow: 0 1rem 3rem #0004; }
  .ids-entry-dialog::backdrop { background: #102030aa; }
  .ids-entry-dialog :focus-visible, .ids-entry-launcher:focus-visible { outline: 3px solid #2368d1; outline-offset: 3px; }
  .ids-entry-actions { display: flex; flex-wrap: wrap; gap: .75rem; margin-top: 1.5rem; }
  .ids-entry-actions button { min-height: 2.75rem; padding: .5rem 1rem; font: inherit; cursor: pointer; }
  @media (max-width: 30rem) { .ids-entry-dialog { width: calc(100vw - 1rem); padding: 1rem; } .ids-entry-actions { flex-direction: column; } }
`;

function installStyles(doc) {
  if (doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement("style");
  style.id = STYLE_ID;
  style.textContent = styles;
  doc.head.append(style);
}

function element(doc, tag, text, attrs = {}) {
  const node = doc.createElement(tag);
  if (text) node.textContent = text;
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  return node;
}

/**
 * Mount an invitation widget. Accept delegates to the host so it can present
 * the consent step before requesting a session bootstrap. Decline is local UI
 * only: this module makes no network request and emits no research event.
 */
export function mountParticipantEntry(root, {
  experienceId,
  invitation,
  onAccept,
  document: doc = globalThis.document,
} = {}) {
  if (!root || typeof root.append !== "function") throw new TypeError("A DOM root element is required");
  if (!doc || !doc.createElement) throw new TypeError("A browser document is required");
  if (typeof experienceId !== "string" || !experienceId.trim()) throw new TypeError("experienceId is required");
  if (!invitation || typeof invitation.title !== "string" || typeof invitation.description !== "string") {
    throw new TypeError("Invitation title and description are required");
  }
  for (const key of ["buttonLabel", "acceptLabel", "declineLabel", "declinedTitle", "declinedDescription", "closeLabel", "startingLabel", "errorMessage"]) {
    if (typeof invitation[key] !== "string" || !invitation[key].trim()) throw new TypeError(`Invitation ${key} is required`);
  }
  if (typeof onAccept !== "function") throw new TypeError("onAccept callback is required");

  installStyles(doc);
  const widgetId = `ids-entry-${++widgetSequence}`;
  const launcher = element(doc, "button", invitation.buttonLabel, { type: "button", class: "ids-entry-launcher" });
  const dialog = element(doc, "dialog", "", { class: "ids-entry-dialog", "aria-labelledby": `${widgetId}-title`, "aria-describedby": `${widgetId}-description` });
  const heading = element(doc, "h2", invitation.title, { id: `${widgetId}-title` });
  const description = element(doc, "p", invitation.description, { id: `${widgetId}-description` });
  const originalTitle = invitation.title;
  const originalDescription = invitation.description;
  const status = element(doc, "p", "", { role: "status", "aria-live": "polite" });
  const actions = element(doc, "div", "", { class: "ids-entry-actions" });
  const accept = element(doc, "button", invitation.acceptLabel, { type: "button" });
  const decline = element(doc, "button", invitation.declineLabel, { type: "button" });
  const close = element(doc, "button", invitation.closeLabel, { type: "button" });
  actions.append(accept, decline);
  dialog.append(heading, description, status, actions);
  root.append(launcher, dialog);

  const widget = {
    state: "ready",
    experienceId,
    destroy() {
      dialog.close?.();
      launcher.remove();
      dialog.remove();
    },
  };

  launcher.addEventListener("click", () => {
    if (widget.state !== "ready" && widget.state !== "declined" && widget.state !== "error") return;
    widget.state = "invitation";
    heading.textContent = originalTitle;
    description.textContent = originalDescription;
    status.textContent = "";
    actions.replaceChildren(accept, decline);
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    accept.focus();
  });

  decline.addEventListener("click", () => {
    widget.state = "declined";
    heading.textContent = invitation.declinedTitle;
    description.textContent = invitation.declinedDescription;
    status.textContent = "No session was started.";
    actions.replaceChildren(close);
    close.focus();
  });

  close.addEventListener("click", () => {
    if (typeof dialog.close === "function") dialog.close();
    else dialog.removeAttribute("open");
    widget.state = "declined";
    launcher.focus();
  });

  accept.addEventListener("click", async () => {
    if (widget.state !== "invitation") return;
    widget.state = "starting";
    status.textContent = invitation.startingLabel;
    accept.disabled = true;
    decline.disabled = true;
    try {
      await onAccept({ experienceId });
      widget.state = "accepted";
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
    } catch (error) {
      widget.state = "error";
      status.textContent = invitation.errorMessage;
      accept.disabled = false;
      decline.disabled = false;
    }
  });

  dialog.addEventListener("cancel", () => {
    widget.state = "ready";
    launcher.focus();
  });
  return widget;
}
