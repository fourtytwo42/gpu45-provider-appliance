"use client";

type ApplianceEventTopic = "telemetry" | "resources" | "operational-jobs";
type EventHandler = (payload: unknown) => void;
type ConnectionHandler = (connected: boolean) => void;

const listeners = new Map<ApplianceEventTopic, Set<EventHandler>>();
const connectionListeners = new Set<ConnectionHandler>();
let source: EventSource | null = null;
let connected = false;

function setConnected(value: boolean): void {
  if (connected === value) return;
  connected = value;
  for (const listener of connectionListeners) listener(value);
}

function ensureSource(): EventSource {
  if (source) return source;
  source = new EventSource("/api/events");
  source.onopen = () => setConnected(true);
  source.onerror = () => setConnected(false);
  for (const topic of ["telemetry", "resources", "operational-jobs"] as ApplianceEventTopic[]) {
    source.addEventListener(topic, (event) => {
      let payload: unknown;
      try { payload = JSON.parse((event as MessageEvent).data); } catch { return; }
      for (const listener of listeners.get(topic) ?? []) listener(payload);
    });
  }
  return source;
}

export function subscribeApplianceEvent<T>(topic: ApplianceEventTopic, handler: (payload: T) => void): () => void {
  const topicListeners = listeners.get(topic) ?? new Set<EventHandler>();
  const listener = handler as EventHandler;
  topicListeners.add(listener);
  listeners.set(topic, topicListeners);
  ensureSource();
  return () => { topicListeners.delete(listener); };
}

export function subscribeApplianceConnection(handler: ConnectionHandler): () => void {
  connectionListeners.add(handler);
  handler(connected);
  ensureSource();
  return () => { connectionListeners.delete(handler); };
}
