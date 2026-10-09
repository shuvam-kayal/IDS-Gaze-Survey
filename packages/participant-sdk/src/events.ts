import type { EventEnvelope } from "../../../contracts/typescript/src/index.js";
export function createEvent(input: Omit<EventEnvelope, "schema_version">): EventEnvelope { return { schema_version: "1.0.0", ...input }; }
