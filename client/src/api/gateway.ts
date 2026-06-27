import { Channel, invoke } from "@tauri-apps/api/core";

import type {
  AskRequest,
  AskResponse,
  LayoutDTO,
  OkResponse,
  ReviewItem,
  StatusResponse,
  StreamEvent,
} from "./dto";
import { toApiError } from "./errors";
import type { PendingAction } from "../screens/dtos";

const call = async <T>(command: string, args?: Record<string, unknown>): Promise<T> => {
  try {
    return await invoke<T>(command, args);
  } catch (error: unknown) {
    throw toApiError(error);
  }
};

export const status = (): Promise<StatusResponse> => call("app_status");

export const reviewPending = (): Promise<ReviewItem[]> => call("app_review_pending");

export const reviewAutoEnabled = (): Promise<boolean> => call("app_review_auto_enabled");

export const reviewApprove = (name: string): Promise<OkResponse> =>
  call("app_review_approve", { name });

export const reviewReject = (name: string): Promise<OkResponse> =>
  call("app_review_reject", { name });

export const actionsPending = (): Promise<PendingAction[]> => call("app_actions_pending");

export const actionApprove = (id: string): Promise<OkResponse> =>
  call("app_actions_approve", { id });

export const actionReject = (id: string): Promise<OkResponse> =>
  call("app_actions_reject", { id });

export const ask = (request: AskRequest): Promise<AskResponse> => call("app_ask", { request });

export const lock = (): Promise<OkResponse> => call("app_lock");

export const logout = (): Promise<OkResponse> => call("app_logout");

export const layoutGet = (): Promise<LayoutDTO> => call("app_layout_get");

export const layoutPut = (layout: LayoutDTO): Promise<LayoutDTO> =>
  call("app_layout_put", { layout });

export async function* askStream(request: AskRequest): AsyncGenerator<StreamEvent> {
  const queue: StreamEvent[] = [];
  let resolveNext: (() => void) | null = null;
  let finished = false;

  const wake = (): void => {
    resolveNext?.();
    resolveNext = null;
  };

  const channel = new Channel<StreamEvent>();
  channel.onmessage = (event) => {
    queue.push(event);
    if (event.type === "done" || event.type === "vault_locked") {
      finished = true;
    }
    wake();
  };

  await call<void>("app_ask_stream", { request, channel });

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
