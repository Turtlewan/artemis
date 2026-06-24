import { useSyncExternalStore } from "react";

import { askStream } from "../api/gateway";
import { connectionStore } from "../state/connection";
import type { AskEngine } from "./EngineTag";

export type AskRole = "user" | "assistant";
export type AskModeHint = "TASK" | "DIGEST" | "WIND-DOWN";

export interface AskMessage {
  id: string;
  role: AskRole;
  text: string;
  engine?: AskEngine;
  path?: string;
  tool?: string;
  failedLocked?: boolean;
}

export interface AskEngineStatus {
  local: boolean;
  codex: boolean;
  review: boolean;
}

export interface AskSnapshot {
  messages: AskMessage[];
  streaming: string;
  modeHint: AskModeHint;
  engineStatus: AskEngineStatus;
  politeAnnouncement: string;
  assertiveAnnouncement: string;
  sending: boolean;
}

type Listener = () => void;
type UnlockPrompt = () => void;

const initialSnapshot = (): AskSnapshot => ({
  messages: [],
  streaming: "",
  modeHint: "TASK",
  engineStatus: { local: true, codex: false, review: false },
  politeAnnouncement: "",
  assertiveAnnouncement: "",
  sending: false,
});

let snapshot = initialSnapshot();
let nextId = 0;
let unlockPrompt: UnlockPrompt = () => {
  window.dispatchEvent(new CustomEvent("artemis:reunlock-required"));
};

const listeners = new Set<Listener>();

const emit = (): void => {
  for (const listener of listeners) listener();
};

const update = (patch: Partial<AskSnapshot>): void => {
  snapshot = { ...snapshot, ...patch };
  emit();
};

const id = (): string => {
  nextId += 1;
  return `ask-${nextId}`;
};

const deriveEngine = (path?: string, escalated?: boolean): AskEngine => {
  if (escalated === true) return "review";
  if (path !== undefined && path !== "" && path !== "local" && path !== "direct") return "codex";
  return "local";
};

const sentenceBoundary = /[.!?]\s*$/u;

const publishPolite = (text: string, force = false): void => {
  if (force || sentenceBoundary.test(text)) {
    update({ politeAnnouncement: text });
  }
};

const appendMessage = (message: AskMessage): void => {
  update({ messages: [...snapshot.messages, message] });
};

const replaceMessage = (messageId: string, replacement: AskMessage): void => {
  update({
    messages: snapshot.messages.map((message) => (message.id === messageId ? replacement : message)),
  });
};

const markEngine = (engine: AskEngine): void => {
  update({ engineStatus: { ...snapshot.engineStatus, [engine]: true } });
};

export const askStore = {
  getSnapshot: (): AskSnapshot => snapshot,
  subscribe: (listener: Listener): (() => void) => {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
  setUnlockPromptForTest: (prompt: UnlockPrompt): void => {
    unlockPrompt = prompt;
  },
  resetForTest: (): void => {
    snapshot = initialSnapshot();
    nextId = 0;
    unlockPrompt = () => undefined;
    emit();
  },
  async send(text: string): Promise<void> {
    const trimmed = text.trim();
    if (trimmed === "") return;

    if (connectionStore.getSnapshot().state !== "unlocked") {
      unlockPrompt();
      update({ assertiveAnnouncement: "Vault locked - re-authentication required" });
      return;
    }

    const assistantId = id();
    appendMessage({ id: id(), role: "user", text: trimmed });
    appendMessage({ id: assistantId, role: "assistant", text: "", engine: "local" });
    update({ streaming: "", sending: true, assertiveAnnouncement: "" });

    let streamed = "";
    try {
      for await (const event of askStream({ text: trimmed })) {
        if (event.type === "text") {
          streamed += event.text;
          update({ streaming: streamed });
          publishPolite(streamed);
          continue;
        }

        if (event.type === "vault_locked") {
          unlockPrompt();
          replaceMessage(assistantId, {
            id: assistantId,
            role: "assistant",
            text: streamed,
            engine: "local",
            failedLocked: true,
          });
          update({
            streaming: "",
            sending: false,
            assertiveAnnouncement: "Vault locked - re-authentication required",
          });
          return;
        }

        const engine = deriveEngine(event.path, event.escalated);
        markEngine(engine);
        replaceMessage(assistantId, {
          id: assistantId,
          role: "assistant",
          text: streamed,
          engine,
          path: event.path,
          tool: event.tool_used ?? undefined,
        });
        update({ streaming: "", sending: false });
        publishPolite(streamed, true);
      }
    } finally {
      if (snapshot.sending) update({ sending: false });
    }
  },
};

export const useAskStore = <T,>(selector: (current: AskSnapshot) => T): T => {
  return useSyncExternalStore(
    askStore.subscribe,
    () => selector(askStore.getSnapshot()),
    () => selector(askStore.getSnapshot()),
  );
};
