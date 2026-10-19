import type { EventEnvelope } from "../../../contracts/typescript/src/index.js";
export interface EventQueueOptions {
  endpoint: string;
  fetchImpl?: typeof fetch;
  maxQueueSize?: number;
  maxQueueBytes?: number;
  baseDelayMs?: number;
  maxDelayMs?: number;
  maxRetriesPerFlush?: number;
  sleep?: (milliseconds: number) => Promise<void>;
}
export interface EventQueueFlushResult { delivered: number; remaining: number; error: Error | null }
export class EventQueue {
  constructor(options: EventQueueOptions);
  readonly size: number;
  enqueue(event: EventEnvelope): { queued: boolean; duplicate: boolean; size: number };
  flush(options?: { keepalive?: boolean }): Promise<EventQueueFlushResult>;
  attachLifecycle(options?: { window?: Window; document?: Document }): () => void;
  purge(): void;
  close(): Promise<EventQueueFlushResult>;
}
