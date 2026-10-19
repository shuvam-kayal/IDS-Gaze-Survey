let flowSequence = 0;

function textElement(doc, tag, text, attrs = {}) {
  const node = doc.createElement(tag);
  if (text) node.textContent = text;
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  return node;
}

/** Render sequential research and camera consent choices from server policy text. */
export function mountConsentFlow(root, { controller, policy, labels, cameraOptions, onContinue = () => {}, document: doc = globalThis.document } = {}) {
  if (!root || typeof root.replaceChildren !== "function") throw new TypeError("A consent-flow root element is required");
  if (!controller || typeof controller.recordResearchConsent !== "function" || typeof controller.recordCameraConsent !== "function" || typeof controller.withdraw !== "function") {
    throw new TypeError("A ConsentLifecycle controller is required");
  }
  if (!policy?.research || !policy?.camera || typeof policy.camera.offered !== "boolean") {
    throw new TypeError("Server-provided research and camera consent policy is required");
  }
  if (!labels || !doc?.createElement) throw new TypeError("Consent labels and browser document are required");

  const flowId = `ids-consent-${++flowSequence}`;
  const flow = { state: "research_consent", root, controller, policy, labels, document: doc, cameraOptions, onContinue };
  const status = textElement(doc, "p", "", { role: "status", "aria-live": "polite" });

  function render({ title, description, actions }) {
    status.textContent = "";
    const panel = textElement(doc, "section", "", { "aria-labelledby": `${flowId}-title` });
    panel.append(textElement(doc, "h2", title, { id: `${flowId}-title` }));
    panel.append(textElement(doc, "p", description, { id: `${flowId}-description` }));
    panel.setAttribute("aria-describedby", `${flowId}-description`);
    const actionGroup = textElement(doc, "div", "", { class: "ids-consent-actions" });
    for (const button of actions) actionGroup.append(button);
    panel.append(actionGroup, status);
    if (controller.canCollectResearch || flow.state === "camera_consent" || flow.state === "complete") {
      const withdraw = textElement(doc, "button", labels.withdraw, { type: "button" });
      withdraw.addEventListener("click", async () => {
        for (const control of panel.querySelectorAll("button")) control.disabled = true;
        flow.state = "withdrawing";
        status.textContent = labels.withdrawing;
        const result = await controller.withdraw();
        showWithdrawn(result.audit_status);
      });
      panel.append(withdraw);
    }
    root.replaceChildren(panel);
  }

  function button(label, action) {
    const control = textElement(doc, "button", label, { type: "button" });
    control.addEventListener("click", async () => {
      for (const sibling of control.parentElement?.querySelectorAll("button") ?? [control]) sibling.disabled = true;
      await action();
    });
    return control;
  }

  function showWithdrawn(auditStatus) {
    flow.state = "withdrawn";
    render({ title: labels.completeTitle, description: labels.withdrawnDescription, actions: [] });
    status.textContent = auditStatus === "sent" ? labels.withdrawn : labels.withdrawnAuditUnavailable;
    if (auditStatus === "failed" && labels.retryWithdrawalAudit) {
      const retry = button(labels.retryWithdrawalAudit, async () => {
        flow.state = "retrying_withdrawal_audit";
        status.textContent = labels.withdrawing;
        const result = await controller.withdraw();
        showWithdrawn(result.audit_status);
      });
      root.querySelector("section")?.append(retry);
    }
  }

  function cameraMessage(result) {
    const messages = {
      denied: labels.cameraDenied,
      unavailable: labels.cameraUnavailable,
      unsupported: labels.cameraUnsupported,
      interrupted: labels.cameraInterrupted,
      unplugged: labels.cameraUnplugged,
      revoked: labels.cameraRevoked,
      provider_failed: labels.providerFailed,
    };
    return messages[result.status] || labels.cameraUnavailable;
  }

  function continueJourney(modality = "non_gaze_only", missingness = controller.snapshot().camera.missingness || "gaze.not_collected_by_policy") {
    flow.state = "complete";
    Promise.resolve(onContinue({ modality, missingness })).catch(() => {});
    render({ title: labels.completeTitle, description: labels.completeWithoutCameraDescription, actions: [] });
  }

  function renderCameraReady() {
    flow.state = "camera_ready";
    render({
      title: labels.completeTitle,
      description: labels.cameraReadyToStart,
      actions: [
        button(labels.startCamera, async () => {
          flow.state = "starting_camera";
          status.textContent = labels.cameraStarting;
          let result;
          try {
            result = await controller.startCamera({
              ...cameraOptions,
              onCameraStatus: (cameraState) => {
                cameraOptions?.onCameraStatus?.(cameraState);
                if (["denied", "unavailable", "unsupported", "interrupted", "unplugged", "revoked", "provider_failed"].includes(cameraState.status)) {
                  flow.state = "camera_fallback";
                  renderCameraFallback(cameraState);
                }
              },
            });
          } catch {
            result = { status: "provider_failed", modality: "non_gaze_only", reason: "gaze.provider_failure", recoverable: true };
          }
          if (result.modality === "gaze_and_non_gaze") {
            flow.state = "camera_active";
            Promise.resolve(onContinue({ modality: "gaze_and_non_gaze", missingness: null })).catch(() => {});
            render({ title: labels.completeTitle, description: labels.cameraActive, actions: [] });
          } else {
            flow.state = "camera_fallback";
            renderCameraFallback(result);
          }
        }),
        button(labels.continueWithoutGaze, async () => {
          continueJourney();
        }),
      ],
    });
  }

  function renderCameraFallback(result) {
    flow.state = "camera_fallback";
    render({
      title: labels.completeTitle,
      description: cameraMessage(result),
      actions: [
        ...(result.recoverable && cameraOptions ? [button(labels.retryCamera, () => renderCameraReady())] : []),
        button(labels.continueWithoutGaze, async () => {
          continueJourney("non_gaze_only", result.reason || controller.snapshot().camera.missingness || "gaze.camera_unavailable");
        }),
      ],
    });
  }

  function wasWithdrawn() {
    return controller.snapshot().withdrawal.withdrawn;
  }

  async function chooseResearch(decision) {
    flow.state = "saving_research_consent";
    status.textContent = labels.saving;
    try {
      await controller.recordResearchConsent(decision);
      if (decision === "declined") {
        flow.state = "research_declined";
        render({ title: labels.declinedTitle, description: labels.declinedDescription, actions: [] });
        return;
      }
      if (policy.camera.offered) {
        flow.state = "camera_consent";
        renderCameraConsent();
      } else {
        continueJourney("non_gaze_only", "gaze.not_collected_by_policy");
      }
    } catch {
      if (wasWithdrawn()) {
        showWithdrawn(controller.snapshot().withdrawal.audit_status);
        return;
      }
      flow.state = "research_consent";
      status.textContent = labels.saveFailed;
      renderResearchConsent();
      status.textContent = labels.saveFailed;
    }
  }

  async function chooseCamera(decision) {
    flow.state = "saving_camera_consent";
    status.textContent = labels.saving;
    try {
      await controller.recordCameraConsent(decision);
      if (decision === "accepted" && cameraOptions) renderCameraReady();
      else if (decision === "accepted") {
        flow.state = "complete";
        render({ title: labels.completeTitle, description: labels.completeWithCameraDescription, actions: [] });
      }
      else {
        continueJourney("non_gaze_only", "gaze.not_collected_by_policy");
      }
    } catch {
      if (wasWithdrawn()) {
        showWithdrawn(controller.snapshot().withdrawal.audit_status);
        return;
      }
      flow.state = "camera_consent";
      status.textContent = labels.saveFailed;
      renderCameraConsent();
      status.textContent = labels.saveFailed;
    }
  }

  function renderResearchConsent() {
    render({
      title: labels.researchTitle,
      description: policy.research.text,
      actions: [
        button(labels.acceptResearch, () => chooseResearch("accepted")),
        button(labels.declineResearch, () => chooseResearch("declined")),
      ],
    });
  }

  function renderCameraConsent() {
    render({
      title: labels.cameraTitle,
      description: policy.camera.text,
      actions: [
        button(labels.acceptCamera, () => chooseCamera("accepted")),
        button(labels.declineCamera, () => chooseCamera("declined")),
      ],
    });
  }

  renderResearchConsent();
  flow.destroy = () => {
    root.replaceChildren();
    return controller.shutdown();
  };
  return flow;
}
