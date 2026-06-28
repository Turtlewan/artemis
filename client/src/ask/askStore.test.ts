import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  askStream: vi.fn(),
}));

vi.mock("../api/gateway", () => ({
  askStream: mocks.askStream,
}));

import { connectionStore } from "../state/connection";
import { askStore } from "./askStore";

describe("askStore", () => {
  beforeEach(() => {
    mocks.askStream.mockReset();
    connectionStore.resetForTest();
    askStore.resetForTest();
  });

  it("streams text into one assistant message and finalizes engine metadata from done", async () => {
    connectionStore.onPaired();
    connectionStore.onConnected();
    mocks.askStream.mockImplementationOnce(async function* () {
      yield { type: "text", text: "Hello " };
      yield { type: "text", text: "there." };
      yield { type: "done", path: "cloud", tool_used: undefined, escalated: false };
    });

    await askStore.send("status");

    const snapshot = askStore.getSnapshot();
    expect(mocks.askStream).toHaveBeenCalledWith({ text: "status", speak: true });
    expect(snapshot.messages).toMatchObject([
      { role: "user", text: "status" },
      { role: "assistant", text: "Hello there.", engine: "codex", path: "cloud" },
    ]);
    expect(snapshot.messages.filter((message) => message.role === "assistant")).toHaveLength(1);
    expect(snapshot.engineStatus.codex).toBe(true);
    expect(snapshot.politeAnnouncement).toBe("Hello there.");
  });

  it("sends speak false after mute is toggled and remembers the toggle state", async () => {
    connectionStore.onPaired();
    connectionStore.onConnected();
    mocks.askStream.mockImplementation(async function* () {
      yield { type: "done", path: "local", escalated: false };
    });

    expect(askStore.getSnapshot().muted).toBe(false);
    askStore.toggleMute();
    expect(askStore.getSnapshot().muted).toBe(true);

    await askStore.send("quiet");

    expect(mocks.askStream).toHaveBeenCalledWith({ text: "quiet", speak: false });
    expect(askStore.getSnapshot().muted).toBe(true);
  });

  it("blocks disconnected sends without calling the gateway", async () => {
    const raiseUnlock = vi.fn();
    connectionStore.onPaired();
    askStore.setUnlockPromptForTest(raiseUnlock);

    await askStore.send("disconnected question");

    expect(mocks.askStream).not.toHaveBeenCalled();
    expect(raiseUnlock).toHaveBeenCalledTimes(1);
    expect(askStore.getSnapshot().assertiveAnnouncement).toContain("Not connected");
  });

  it("marks a streaming vault lock as failed and assertive without finalizing", async () => {
    const raiseUnlock = vi.fn();
    connectionStore.onPaired();
    connectionStore.onConnected();
    askStore.setUnlockPromptForTest(raiseUnlock);
    mocks.askStream.mockImplementationOnce(async function* () {
      yield { type: "text", text: "partial" };
      yield { type: "vault_locked" };
    });

    await askStore.send("secret");

    const assistant = askStore.getSnapshot().messages.find((message) => message.role === "assistant");
    expect(assistant).toMatchObject({ text: "", failedLocked: true });
    expect(raiseUnlock).toHaveBeenCalledTimes(1);
    expect(askStore.getSnapshot().assertiveAnnouncement).toContain("Vault locked");
    expect(askStore.getSnapshot().engineStatus.codex).toBe(false);
  });
});
