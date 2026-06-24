import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  askStream: vi.fn(),
}));

vi.mock("../api/gateway", () => ({
  askStream: mocks.askStream,
}));

import { connectionStore } from "../state/connection";
import { askStore } from "./askStore";

async function* stream(events: Array<{ type: "text"; text: string } | { type: "done"; path?: string; escalated?: boolean }>) {
  for (const event of events) yield event;
}

describe("askStore", () => {
  beforeEach(() => {
    mocks.askStream.mockReset();
    connectionStore.resetForTest();
    askStore.resetForTest();
  });

  it("consumes text events and finalizes engine metadata from Done", async () => {
    connectionStore.onPaired();
    connectionStore.onConnected();
    connectionStore.onUnlocked();
    mocks.askStream.mockReturnValueOnce(
      stream([
        { type: "text", text: "Hello " },
        { type: "text", text: "there." },
        { type: "done", path: "cloud", escalated: false },
      ]),
    );

    await askStore.send("status");

    const snapshot = askStore.getSnapshot();
    expect(mocks.askStream).toHaveBeenCalledWith({ text: "status" });
    expect(snapshot.messages).toMatchObject([
      { role: "user", text: "status" },
      { role: "assistant", text: "Hello there.", engine: "codex", path: "cloud" },
    ]);
    expect(snapshot.engineStatus.codex).toBe(true);
    expect(snapshot.politeAnnouncement).toBe("Hello there.");
  });

  it("blocks locked sends and raises the re-unlock seam without streaming", async () => {
    const raiseUnlock = vi.fn();
    connectionStore.onPaired();
    connectionStore.onConnected();
    askStore.setUnlockPromptForTest(raiseUnlock);

    await askStore.send("locked question");

    expect(mocks.askStream).not.toHaveBeenCalled();
    expect(raiseUnlock).toHaveBeenCalledTimes(1);
    expect(askStore.getSnapshot().assertiveAnnouncement).toContain("Vault locked");
  });

  it("marks an in-flight vault lock as failed and assertive", async () => {
    const raiseUnlock = vi.fn();
    connectionStore.onPaired();
    connectionStore.onConnected();
    connectionStore.onUnlocked();
    askStore.setUnlockPromptForTest(raiseUnlock);
    mocks.askStream.mockReturnValueOnce(
      (async function* lockedStream() {
        yield { type: "text" as const, text: "Partial" };
        yield { type: "vault_locked" as const };
      })(),
    );

    await askStore.send("secret");

    const assistant = askStore.getSnapshot().messages.find((message) => message.role === "assistant");
    expect(assistant).toMatchObject({ text: "Partial", failedLocked: true });
    expect(raiseUnlock).toHaveBeenCalledTimes(1);
    expect(askStore.getSnapshot().assertiveAnnouncement).toContain("Vault locked");
  });
});
