import { invoke } from "@tauri-apps/api/core";

import { toApiError } from "./errors";

export interface ModelConstraints {
  no_tools: boolean;
  temperature: number | null;
}

export interface ModelRole {
  role: string;
  provider: string;
  model: string;
  constraints: ModelConstraints;
  eligible_providers: string[];
  editable_fields: string[];
}

export interface DroppedOverride {
  role: string;
  reason: string;
}

export interface ModelsResponse {
  roles: ModelRole[];
  providers: string[];
  dropped_overrides: DroppedOverride[];
}

export interface RoleInvalid {
  detail: string;
}

/** PUT result: the new binding, or a 422 rejection carrying the brain's message verbatim. */
export type RolePutResponse = ModelRole | RoleInvalid;

export interface ModelUsage {
  role: string;
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  avg_latency_ms: number;
}

export interface ModelUsageResponse {
  roles: ModelUsage[];
}

const call = async <T>(command: string, args?: Record<string, unknown>): Promise<T> => {
  try {
    return await invoke<T>(command, args);
  } catch (error: unknown) {
    throw toApiError(error);
  }
};

/** List every model role with its binding, constraints, eligible providers, and dropped overrides. */
export const modelsGet = (): Promise<ModelsResponse> => call("app_models_get");

/** Update one role's provider/model binding. Returns the new binding, or {detail} on a 422 rejection. */
export const modelsPut = (
  role: string,
  provider: string,
  model: string,
): Promise<RolePutResponse> => call("app_models_put", { role, provider, model });

/** Per-role usage aggregates (calls, tokens, average latency). */
export const modelsUsage = (): Promise<ModelUsageResponse> => call("app_models_usage");

/** Narrow a PUT result to the 422-rejection arm. */
export const isRoleInvalid = (response: RolePutResponse): response is RoleInvalid =>
  "detail" in response;
