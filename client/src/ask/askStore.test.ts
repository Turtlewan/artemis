import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  ask: vi.fn(),
}));

vi.mock("../api/gateway", () => ({
  ask: mocks.ask,
}));

import { connectionStore } from "../state/connection";
import { askStore } from "./askStore";

describe("askStore", () => {
  beforeEach(() => {
    mocks.ask.mockReset();
    connectionStore.resetForTest();
    askStore.resetForTest();
  });

  it("sends app_ask and finalizes engine metadata from the response", async () => {
    connectionStore.onPaired();
    connectionStore.onConnected();
    mocks.ask.mockResolvedValueOnce({
      text: "Hello there.",
      path: "cloud",
      tool_used: null,
      escalated: false,
    });

    await askStore.send("status");

    const snapshot = askStore.getSnapshot();
    expect(mocks.ask).toHaveBeenCalledWith({ text: "status" });
    expect(snapshot.messages).toMatchObject([
      { role: "user", text: "status" },
      { role: "assistant", text: "Hello there.", engine: "codex", path: "cloud" },
    ]);
    expect(snapshot.engineStatus.codex).toBe(true);
    expect(snapshot.politeAnnouncement).toBe("Hello there.");
  });

  it("blocks disconnected sends without calling the gateway", async () => {
    const raiseUnlock = vi.fn();
    connectionStore.onPaired();
    askStore.setUnlockPromptForTest(raiseUnlock);

    await askStore.send("disconnected question");

    expect(mocks.ask).not.toHaveBeenCalled();
    expect(raiseUnlock).toHaveBeenCalledTimes(1);
    expect(askStore.getSnapshot().assertiveAnnouncement).toContain("Not connected");
  });

  it("marks a backend vault lock as failed and assertive", async () => {
    const raiseUnlock = vi.fn();
    connectionStore.onPaired();
    connectionStore.onConnected();
    askStore.setUnlockPromptForTest(raiseUnlock);
    mocks.ask.mockRejectedValueOnce({ kind: "vaultLocked" });

    await askStore.send("secret");

    const assistant = askStore.getSnapshot().messages.find((message) => message.role === "assistant");
    expect(assistant).toMatchObject({ text: "", failedLocked: true });
    expect(raiseUnlock).toHaveBeenCalledTimes(1);
    expect(askStore.getSnapshot().assertiveAnnouncement).toContain("Vault locked");
  });
});
