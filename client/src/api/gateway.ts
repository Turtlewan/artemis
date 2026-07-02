import { Channel, invoke } from "@tauri-apps/api/core";

import type {
  AskRequest,
  AskResponse,
  BuildPlanCard,
  BuildStreamEvent,
  InstalledCard,
  InvokeConfirmResponse,
  LayoutDTO,
  OkResponse,
  ReviewItem,
  SecretNamesResponse,
  StatusResponse,
  StreamEvent,
} from "./dto";
import { toApiError } from "./errors";
import type { PendingAction } from "../screens/dtos";

export interface TaskSuggestionAcceptResponse {
  task: Record<string, unknown>;
}

const call = async <T>(command: string, args?: Record<string, unknown>): Promise<T> => {
  try {
    return await invoke<T>(command, args);
  } catch (error: unknown) {
    throw toApiError(error);
  }
};

/** Return the current brain connection and vault status. */
export const status = (): Promise<StatusResponse> => call("app_status");

/** Return recipes currently awaiting owner review. */
export const reviewPending = (): Promise<ReviewItem[]> => call("app_review_pending");

/** Return recipes that have been automatically enabled. */
export const reviewAutoEnabled = (): Promise<ReviewItem[]> => call("app_review_auto_enabled");

/** Approve a recipe by name, moving it from pending to enabled. */
export const reviewApprove = (name: string): Promise<OkResponse> =>
  call("app_review_approve", { name });

/** Reject a recipe by name, retiring it from the review queue. */
export const reviewReject = (name: string): Promise<OkResponse> =>
  call("app_review_reject", { name });

/** Return one-off actions awaiting owner approval. */
export const actionsPending = (): Promise<PendingAction[]> => call("app_actions_pending");

/** Approve a pending action by id, executing it once. */
export const actionApprove = (id: string): Promise<OkResponse> =>
  call("app_actions_approve", { id });

/** Reject a pending action by id without executing it. */
export const actionReject = (id: string): Promise<OkResponse> =>
  call("app_actions_reject", { id });

/** Accept a task suggestion with an optional due date. */
export const acceptSuggestion = (
  id: string,
  dueAt?: string,
): Promise<TaskSuggestionAcceptResponse> =>
  call("task_suggestion_accept", { suggestionId: id, dueAt });

/** Reject a task suggestion without creating a task. */
export const rejectSuggestion = (id: string): Promise<OkResponse> =>
  call("task_suggestion_reject", { suggestionId: id });

/** Send a text Ask request and return the completed answer. */
export const ask = (request: AskRequest): Promise<AskResponse> => call("app_ask", { request });

/** Lock owner data and clear the local session token. */
export const lock = (): Promise<OkResponse> => call("app_lock");

/** Revoke the current API session. */
export const logout = (): Promise<OkResponse> => call("app_logout");

/** Fetch the stored spatial layout. */
export const layoutGet = (): Promise<LayoutDTO> => call("app_layout_get");

/** Persist a new spatial layout using last-writer-wins semantics. */
export const layoutPut = (layout: LayoutDTO): Promise<LayoutDTO> =>
  call("app_layout_put", { layout });

async function* streamCommand<E extends { type: string }>(
  command: string,
  args: (channel: Channel<E>) => Record<string, unknown>,
  isFinal: (event: E) => boolean,
): AsyncGenerator<E> {
  const queue: E[] = [];
  let resolveNext: (() => void) | null = null;
  let finished = false;

  const wake = (): void => {
    resolveNext?.();
    resolveNext = null;
  };

  const channel = new Channel<E>();
  channel.onmessage = (event) => {
    queue.push(event);
    if (isFinal(event)) {
      finished = true;
    }
    wake();
  };

  await call<void>(command, args(channel));

  while (!finished || queue.length > 0) {
    if (queue.length === 0) {
      await new Promise<void>((resolve) => {
        resolveNext = resolve;
      });
    }
    const event = queue.shift();
    if (event !== undefined) {
      yield event;
    }
  }
}

/** Stream a text Ask request as typed SSE events yielded asynchronously. */
export async function* askStream(request: AskRequest): AsyncGenerator<StreamEvent> {
  yield* streamCommand<StreamEvent>(
    "app_ask_stream",
    (channel) => ({ request, channel }),
    (event) => event.type === "done" || event.type === "vault_locked",
  );
}

/** Trigger a push-to-talk voice Ask and stream the answer as typed SSE events. @param speak - whether the brain should also speak the answer aloud. */
export async function* askVoice(speak: boolean): AsyncGenerator<StreamEvent> {
  yield* streamCommand<StreamEvent>(
    "app_ask_voice",
    (channel) => ({ speak, channel }),
    (event) => event.type === "done" || event.type === "vault_locked",
  );
}

export const capabilityPropose = (goal: string): Promise<BuildPlanCard> =>
  call("app_capability_propose", { goal });

export const capabilityPromote = (buildId: string): Promise<InstalledCard> =>
  call("app_capability_promote", { buildId });

export const invokeConfirm = (invokeId: string): Promise<InvokeConfirmResponse> =>
  call("app_invoke_confirm", { invokeId });

export const secretSet = (name: string, value: string): Promise<void> =>
  call("app_secret_set", { name, value });

export const secretList = async (): Promise<string[]> => {
  const response = await call<string[] | SecretNamesResponse>("app_secret_list");
  return Array.isArray(response) ? response : response.names;
};

export const secretDelete = (name: string): Promise<void> =>
  call("app_secret_delete", { name });

export async function* capabilityBuild(buildId: string): AsyncGenerator<BuildStreamEvent> {
  yield* streamCommand<BuildStreamEvent>(
    "app_capability_build",
    (channel) => ({ buildId, channel }),
    (event) => event.type === "done" || event.type === "error",
  );
}
