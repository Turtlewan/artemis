import { invoke } from "@tauri-apps/api/core";

import { toApiError } from "./errors";

export interface BlessEntry {
  name: string;
  current_version: number | null;
  blessed_version: number | null;
  blessed: boolean;
}

const call = async <T>(command: string, args?: Record<string, unknown>): Promise<T> => {
  try {
    return await invoke<T>(command, args);
  } catch (error: unknown) {
    throw toApiError(error);
  }
};

export const blessList = (): Promise<BlessEntry[]> => call("app_bless_list");

export const blessSet = (name: string): Promise<BlessEntry> => call("app_bless_set", { name });

export const blessClear = (name: string): Promise<void> => call("app_bless_clear", { name });
