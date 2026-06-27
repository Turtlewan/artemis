import { invoke } from "@tauri-apps/api/core";
import { beforeEach, describe, expect, test, vi } from "vitest";

import { connectionStore } from "../state/connection";
import { pairDevice, toPairingError } from "./pairing";
import { recoverWithPassphrase } from "./recovery";

vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn(),
}));

const mockedInvoke = vi.mocked(invoke);

describe("pairDevice", () => {
  beforeEach(() => {
    connectionStore.resetForTest();
    mockedInvoke.mockReset();
  });

  test("pairs connects and unlocks in order", async () => {
    mockedInvoke.mockResolvedValue({});

    await pairDevice("123456");

    expect(mockedInvoke).toHaveBeenNthCalledWith(1, "auth_pair", { pairingCode: "123456" });
    expect(mockedInvoke).toHaveBeenNthCalledWith(2, "auth_connect");
    expect(mockedInvoke).toHaveBeenNthCalledWith(3, "auth_unlock");
    expect(connectionStore.getSnapshot().state).toBe("unlocked");
  });

  test("surfaces wrong or expired pairing code", async () => {
    mockedInvoke.mockRejectedValueOnce({ kind: "pairingRejected" });

    await expect(pairDevice("expired")).rejects.toEqual({ kind: "wrongOrExpiredCode" });
    expect(connectionStore.getSnapshot().state).toBe("unpaired");
  });

  test("surfaces off tunnel errors", async () => {
    mockedInvoke.mockRejectedValueOnce({ kind: "network" });

    await expect(pairDevice("123456")).rejects.toEqual({ kind: "offTunnel" });
  });

  test("surfaces biometric cancellation", async () => {
    mockedInvoke.mockRejectedValueOnce({ kind: "biometricCancelled" });

    await expect(pairDevice("123456")).rejects.toEqual({ kind: "biometricCancelled" });
  });
});

describe("toPairingError", () => {
  test("maps http auth failures to code rejection", () => {
    expect(toPairingError({ kind: "http", status: 410 })).toEqual({
      kind: "wrongOrExpiredCode",
    });
  });
});

describe("recoverWithPassphrase", () => {
  beforeEach(() => {
    mockedInvoke.mockReset();
  });

  test("invokes recovery without retaining a mutable local copy", async () => {
    mockedInvoke.mockResolvedValue({});

    await recoverWithPassphrase("recovery secret");

    expect(mockedInvoke).toHaveBeenCalledWith("auth_recover", {
      passphrase: "recovery secret",
    });
  });
});
