import type { EventEnvelope } from "../../../contracts/typescript/src/index.js";

export type InteractionEventType = "interaction.click" | "interaction.hover" | "interaction.scroll" | "interaction.navigation" | "page.visibility_changed";
export interface InteractionEvent extends EventEnvelope { event_type: InteractionEventType }
export interface InteractionCapturePolicy { version: string; allowed_event_types: InteractionEventType[] }
export interface InteractionCapture {
  recordNavigation(): InteractionEvent | null;
  stop(): void;
}
export function startInteractionCapture(options: {
  context: { experience_id: string; study_ids: string[]; session_id: string; participant_id?: string | null };
  policy: InteractionCapturePolicy;
  allowedAoiIds: string[];
  controller: { registerListener(target: EventTarget, eventName: string, listener: EventListener, options?: boolean | AddEventListenerOptions): () => boolean; registerCollector(stop: () => void): () => boolean };
  onEvent: (event: InteractionEvent) => void;
  resolveAoiId?: (target: Element) => string | null;
  eventId?: () => string;
  wallClock?: () => Date | number | string;
  document?: Document;
  window?: Window;
}): InteractionCapture;
export function isSensitiveTarget(target: Element | null): boolean;
