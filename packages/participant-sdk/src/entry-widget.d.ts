export interface ParticipantInvitation {
  title: string;
  description: string;
  buttonLabel: string;
  acceptLabel: string;
  declineLabel: string;
  declinedTitle: string;
  declinedDescription: string;
  closeLabel: string;
  startingLabel: string;
  errorMessage: string;
}

export interface ParticipantEntryOptions {
  experienceId: string;
  invitation: ParticipantInvitation;
  onAccept: (context: { experienceId: string }) => void | Promise<void>;
  document?: Document;
}

export interface ParticipantEntryWidget {
  state: "ready" | "invitation" | "declined" | "starting" | "accepted" | "error";
  experienceId: string;
  destroy(): void;
}

export function mountParticipantEntry(root: Element, options: ParticipantEntryOptions): ParticipantEntryWidget;
