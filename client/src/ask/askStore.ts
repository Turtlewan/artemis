import { useSyncExternalStore } from "react";

import * as gateway from "../api/gateway";
import type { BuildPlanCard } from "../api/dto";
import { connectionStore } from "../state/connection";
import type { AskEngine } from "./EngineTag";

export type AskRole = "user" | "assistant";
export type AskModeHint = "TASK" | "DIGEST" | "WIND-DOWN";
export type AskMessageKind = "text" | "plan" | "status" | "result" | "installed" | "invoke_confirm";

export interface AskBuildResult {
  passed: boolean;
  blocked: boolean;
  output: string;
}

export interface AskInvokeConfirm {
  invokeId: string;
  capability: string;
  egressDomains: string[];
  secrets: string[];
  args: Record<string, unknown>;
  missingSecrets: string[];
}

export interface AskMessage {
  id: string;
  role: AskRole;
  text: string;
  kind?: AskMessageKind;
  plan?: BuildPlanCard;
  invoke?: AskInvokeConfirm;
  result?: AskBuildResult;
  buildId?: string;
  engine?: AskEngine;
  path?: string;
  tool?: string;
  verdict?: "passed" | "flagged" | "unjudged";
  verdictReason?: string;
  answeredFrom?: "local_data" | "general_knowledge";
  escalated?: boolean;
  failedLocked?: boolean;
}

export interface AskEngineStatus {
  local: boolean;
  codex: boolean;
  review: boolean;
  loop: boolean;
}

export interface AskSnapshot {
  messages: AskMessage[];
  streaming: string;
  modeHint: AskModeHint;
  engineStatus: AskEngineStatus;
  politeAnnouncement: string;
  assertiveAnnouncement: string;
  sending: boolean;
  buildMode: boolean;
  muted: boolean;
  speaking: boolean;
}

type Listener = () => void;
type UnlockPrompt = () => void;

const initialSnapshot = (): AskSnapshot => ({
  messages: [],
  streaming: "",
  modeHint: "TASK",
  engineStatus: { local: true, codex: false, review: false, loop: false },
  politeAnnouncement: "",
  assertiveAnnouncement: "",
  sending: false,
  buildMode: false,
  muted: false,
  speaking: false,
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
  if (path === "loop") return "loop";
  if (path !== undefined && path !== "" && path !== "local" && path !== "direct") return "codex";
  return "local";
};

const loopCaveats = (message: {
  verdict?: "passed" | "flagged" | "unjudged";
  verdictReason?: string;
  answeredFrom?: "local_data" | "general_knowledge";
  escalated?: boolean;
  path?: string;
}): string[] => {
  const caveats: string[] = [];
  if (message.verdict === "flagged") {
    caveats.push(
      `unverified - couldn't be grounded in your data${
        message.verdictReason !== undefined && message.verdictReason !== ""
          ? ` - ${message.verdictReason}`
          : ""
      }`,
    );
  }
  if (message.verdict === "unjudged" && message.path === "loop") {
    caveats.push("unverified (checker unavailable)");
  }
  if (message.answeredFrom === "general_knowledge") {
    caveats.push("answered from general knowledge - not from your data");
  }
  if (message.escalated === true) {
    caveats.push("retried under a stronger model");
  }
  return caveats;
};

const sentenceBoundary = /[.!?]\s*$/u;

// Conservative build-intent match: an imperative build verb near the start + a capability noun.
// Model-based intent classification is a later upgrade; a false positive only yields a dismissable plan card.
const BUILD_INTENT =
  /^\s*(?:please\s+)?(?:build|create|make|write)\b.*\b(capabilit(?:y|ies)|module|tool|skill|recipe|util(?:ity)?|function)\b/i;
const isBuildIntent = (text: string): boolean => BUILD_INTENT.test(text);

const isConnected = (): boolean => {
  const state = connectionStore.getSnapshot().state;
  return state === "connectedLocked" || state === "unlocked";
};

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

const appendTextToMessage = (messageId: string, text: string): void => {
  update({
    messages: snapshot.messages.map((message) =>
      message.id === messageId ? { ...message, text } : message,
    ),
  });
};

const markEngine = (engine: AskEngine): void => {
  update({ engineStatus: { ...snapshot.engineStatus, [engine]: true } });
};

const isVaultLockedError = (error: unknown): boolean => {
  return (
    typeof error === "object" &&
    error !== null &&
    "kind" in error &&
    (error as { kind?: unknown }).kind === "vaultLocked"
  );
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
  toggleMute: (): void => {
    update({ muted: !snapshot.muted });
  },
  setSpeaking: (speaking: boolean): void => {
    update({ speaking });
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

    if (isBuildIntent(trimmed)) {
      await this.startBuild(trimmed);
      return;
    }

    if (!isConnected()) {
      unlockPrompt();
      update({ assertiveAnnouncement: "Not connected - re-authentication required" });
      return;
    }

    appendMessage({ id: id(), role: "user", text: trimmed });
    update({ streaming: "", sending: true, assertiveAnnouncement: "" });

    try {
      const requestMuted = snapshot.muted;
      const response = await gateway.ask({ text: trimmed, speak: !requestMuted });

      if (response.path === "invoke_confirm" && response.invoke_id !== undefined) {
        appendMessage({
          id: id(),
          role: "assistant",
          text: "",
          kind: "invoke_confirm",
          invoke: {
            invokeId: response.invoke_id,
            capability: response.capability ?? "",
            egressDomains: response.egress_domains ?? [],
            secrets: response.secrets ?? [],
            args: response.args ?? {},
            missingSecrets: [],
          },
        });
        return;
      }

      if (response.path === "invoke_clarify") {
        const missing = response.missing?.join(", ") ?? "";
        appendMessage({
          id: id(),
          role: "assistant",
          text: `I need more detail to run '${response.capability ?? ""}': ${missing}`,
        });
        return;
      }

      const engine = deriveEngine(response.path, response.escalated);
      markEngine(engine);
      const assistantMessage: AskMessage = {
        id: id(),
        role: "assistant",
        text: response.text,
        engine,
        path: response.path,
        tool: response.tool_used ?? undefined,
        verdict: response.verdict ?? undefined,
        verdictReason:
          response.verdict_reason === "" ? undefined : (response.verdict_reason ?? undefined),
        answeredFrom: response.answered_from ?? undefined,
        escalated: response.escalated,
      };
      appendMessage(assistantMessage);
      update({ streaming: "" });
      publishPolite([response.text, ...loopCaveats(assistantMessage)].join(" "), true);
    } catch (error: unknown) {
      if (isVaultLockedError(error)) {
        unlockPrompt();
        appendMessage({
          id: id(),
          role: "assistant",
          text: "",
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
      throw error;
    } finally {
      if (snapshot.sending) update({ sending: false });
    }
  },
  async startBuild(goal: string): Promise<void> {
    const trimmed = goal.trim();
    if (trimmed === "") return;
    if (!isConnected()) {
      unlockPrompt();
      update({ assertiveAnnouncement: "Not connected - re-authentication required" });
      return;
    }
    appendMessage({ id: id(), role: "user", text: trimmed });
    update({ buildMode: true, sending: true, assertiveAnnouncement: "" });
    try {
      const plan = await gateway.capabilityPropose(trimmed);
      appendMessage({
        id: id(),
        role: "assistant",
        text: "",
        kind: "plan",
        plan,
        buildId: plan.build_id,
      });
    } finally {
      update({ sending: false });
    }
  },
  async confirmBuild(buildId: string): Promise<void> {
    const statusId = id();
    appendMessage({ id: statusId, role: "assistant", text: "Starting…", kind: "status", buildId });
    update({ sending: true });
    let result: AskBuildResult | null = null;
    try {
      for await (const event of gateway.capabilityBuild(buildId)) {
        if (event.type === "build_status") {
          appendTextToMessage(statusId, event.text);
        } else if (event.type === "build_result") {
          result = { passed: event.passed, blocked: event.blocked, output: event.output };
        } else if (event.type === "error") {
          appendTextToMessage(statusId, "Build error.");
        }
      }
      if (result !== null) {
        appendMessage({
          id: id(),
          role: "assistant",
          text: "",
          kind: "result",
          result,
          buildId,
        });
      }
    } finally {
      update({ sending: false });
    }
  },
  async promoteBuild(buildId: string): Promise<void> {
    update({ sending: true });
    try {
      const installed = await gateway.capabilityPromote(buildId);
      appendMessage({
        id: id(),
        role: "assistant",
        text: `Added "${installed.name}" (v${installed.version}) — built & verified.`,
        kind: "installed",
      });
    } finally {
      update({ sending: false, buildMode: false });
    }
  },
  cancelBuild(messageId: string): void {
    update({
      messages: snapshot.messages.filter((message) => message.id !== messageId),
      buildMode: false,
    });
  },
  async confirmInvoke(messageId: string): Promise<void> {
    const message = snapshot.messages.find((candidate) => candidate.id === messageId);
    if (message?.invoke === undefined) return;

    update({ sending: true });
    try {
      const result = await gateway.invokeConfirm(message.invoke.invokeId);
      if (result.status === "ok") {
        replaceMessage(messageId, {
          id: messageId,
          role: "assistant",
          text: result.text ?? "",
        });
        return;
      }

      if (result.status === "missing_secrets") {
        replaceMessage(messageId, {
          ...message,
          invoke: { ...message.invoke, missingSecrets: result.missing_secrets },
        });
        return;
      }

      replaceMessage(messageId, {
        id: messageId,
        role: "assistant",
        text:
          result.status === "not_found"
            ? "That request has expired — ask again."
            : "Something went wrong running that.",
      });
    } finally {
      update({ sending: false });
    }
  },
  cancelInvoke(messageId: string): void {
    update({
      messages: snapshot.messages.filter((message) => message.id !== messageId),
    });
  },
};

export const useAskStore = <T,>(selector: (current: AskSnapshot) => T): T => {
  return useSyncExternalStore(
    askStore.subscribe,
    () => selector(askStore.getSnapshot()),
    () => selector(askStore.getSnapshot()),
  );
};
