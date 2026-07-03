import { invoke } from "@tauri-apps/api/core";

import { toApiError } from "./errors";

export interface OAuthConnectStartedResponse {
  consent_url: string;
}

export interface OAuthClientNotConfiguredResponse {
  status: "client_not_configured";
}

export type OAuthConnectResponse =
  | OAuthConnectStartedResponse
  | OAuthClientNotConfiguredResponse;

export interface OAuthStatusResponse {
  account: string;
  connected: boolean;
  granted_scopes: string[];
  connect_pending: boolean;
  last_connect_error: string | null;
}

export interface OAuthDisconnectResponse {
  disconnected: boolean;
}

const call = async <T>(command: string, args?: Record<string, unknown>): Promise<T> => {
  try {
    return await invoke<T>(command, args);
  } catch (error: unknown) {
    throw toApiError(error);
  }
};

/** Start Google OAuth through the local brain; the desktop client never handles tokens. */
export const oauthConnect = (scopes: string[]): Promise<OAuthConnectResponse> =>
  call("app_oauth_connect", { scopes });

/** Return the linked Google account label and granted scopes without token material. */
export const oauthStatus = (): Promise<OAuthStatusResponse> => call("app_oauth_status");

/** Disconnect the linked Google account. */
export const oauthDisconnect = (account?: string): Promise<OAuthDisconnectResponse> =>
  call("app_oauth_disconnect", { account });
