"use client";

export type ApplianceEventTopic = "telemetry" | "resources" | "operational-jobs" | "tts" | "pocket-tts" | "images" | "video" | "whisper";
type EventHandler = (payload: unknown) => void;
type ConnectionHandler = (connected: boolean) => void;

const listeners = new Map<ApplianceEventTopic, Set<EventHandler>>();
const connectionListeners = new Set<ConnectionHandler>();
let source: EventSource | null = null;
let connected = false;
let sourceTopics = "";
let updateScheduled = false;

function setConnected(value: boolean): void {
  if (connected === value) return;
  connected = value;
  for (const listener of connectionListeners) listener(value);
}

function updateSource(): void {
  updateScheduled = false;
  const topics = [...listeners.entries()].filter(([, handlers]) => handlers.size > 0).map(([topic]) => topic).sort();
  const nextTopics = topics.join(",");
  if (source && sourceTopics === nextTopics) return;
  source?.close();
  source = null;
  sourceTopics = nextTopics;
  setConnected(false);
  if (!nextTopics) return;
  source = new EventSource(`/api/events?topics=${encodeURIComponent(nextTopics)}`);
  source.onopen = () => setConnected(true);
  source.onerror = () => setConnected(false);
  for (const topic of topics) {
    source.addEventListener(topic, (event) => {
      let payload: unknown;
      try { payload = JSON.parse((event as MessageEvent).data); } catch { return; }
      for (const listener of listeners.get(topic) ?? []) listener(payload);
    });
  }
}

function scheduleSourceUpdate(): void {
  if (updateScheduled) return;
  updateScheduled = true;
  queueMicrotask(updateSource);
}

export function subscribeApplianceEvent<T>(topic: ApplianceEventTopic, handler: (payload: T) => void): () => void {
  const topicListeners = listeners.get(topic) ?? new Set<EventHandler>();
  const listener = handler as EventHandler;
  topicListeners.add(listener);
  listeners.set(topic, topicListeners);
  scheduleSourceUpdate();
  return () => { topicListeners.delete(listener); scheduleSourceUpdate(); };
}

export function subscribeApplianceConnection(handler: ConnectionHandler): () => void {
  connectionListeners.add(handler);
  handler(connected);
  scheduleSourceUpdate();
  return () => { connectionListeners.delete(handler); };
}
