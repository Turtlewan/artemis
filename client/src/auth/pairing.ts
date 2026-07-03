import { invoke } from "@tauri-apps/api/core";

import { toApiError, type ApiError } from "../api/errors";
import { connectionStore } from "../state/connection";

export type PairingError =
  | { kind: "wrongOrExpiredCode" }
  | { kind: "offTunnel" }
  | { kind: "biometricCancelled" }
  | { kind: "network" };

interface SerializedAuthError {
  kind?: unknown;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null;

const fromApiError = (error: ApiError): PairingError => {
  if (error.kind === "http" && [400, 401, 403, 404, 410].includes(error.status)) {
    return { kind: "wrongOrExpiredCode" };
  }
  if (error.kind === "network") {
    return { kind: "offTunnel" };
  }
  return { kind: "network" };
};

export const toPairingError = (error: unknown): PairingError => {
  if (isRecord(error)) {
    const auth = error as SerializedAuthError;
    if (auth.kind === "biometricCancelled") {
      return { kind: "biometricCancelled" };
    }
    if (auth.kind === "pairingRejected") {
      return { kind: "wrongOrExpiredCode" };
    }
    if (auth.kind === "network" || auth.kind === "hardwareUnavailable") {
      return { kind: "offTunnel" };
    }
  }
  return fromApiError(toApiError(error));
};

export const pairDevice = async (pairingCode: string): Promise<void> => {
  try {
    await invoke("auth_pair", { pairingCode });
    connectionStore.onPaired();
    await invoke("auth_connect");
    connectionStore.onConnected();
    await invoke("auth_unlock");
    connectionStore.onUnlocked();
  } catch (error: unknown) {
    throw toPairingError(error);
  }
};

/**
 * Re-establish a session from the already-stored device key — no pairing code.
 *
 * On app startup (after a webview reload or a brain restart) the device key persists
 * in the keystore and the brain still has the device registered, so only the session
 * bootstrap + unlock are needed; pairing is only for a brand-new device. Returns false
 * when there is no stored device (never paired) or the reconnect is rejected — the
 * caller then shows the pairing screen. Never throws.
 */
export const reconnectDevice = async (): Promise<boolean> => {
  try {
    await invoke("auth_connect");
    connectionStore.onConnected();
    await invoke("auth_unlock");
    connectionStore.onUnlocked();
    return true;
  } catch {
    return false;
  }
};
