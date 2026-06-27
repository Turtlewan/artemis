import { invoke } from "@tauri-apps/api/core";

export const recoverWithPassphrase = async (value: string): Promise<void> => {
  const ref = { passphrase: value };
  try {
    await invoke("auth_recover", { passphrase: ref.passphrase });
  } finally {
    ref.passphrase = "";
  }
};
