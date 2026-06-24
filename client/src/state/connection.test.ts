import { beforeEach, describe, expect, it } from "vitest";

import { connectionStore } from "./connection";

describe("connection state machine", () => {
  beforeEach(() => {
    connectionStore.resetForTest();
  });

  it("follows the paired to unlocked path", () => {
    expect(connectionStore.getSnapshot().state).toBe("unpaired");

    connectionStore.onPaired();
    expect(connectionStore.getSnapshot().state).toBe("disconnected");

    connectionStore.onConnected();
    expect(connectionStore.getSnapshot().state).toBe("connectedLocked");

    connectionStore.onUnlocked();
    expect(connectionStore.getSnapshot().state).toBe("unlocked");
  });

  it("locks, disconnects, and revokes from any active state", () => {
    connectionStore.onPaired();
    connectionStore.onConnected();
    connectionStore.onUnlocked();

    connectionStore.onLocked();
    expect(connectionStore.getSnapshot().state).toBe("connectedLocked");

    connectionStore.onDisconnected();
    expect(connectionStore.getSnapshot().state).toBe("disconnected");

    connectionStore.onRevoked();
    expect(connectionStore.getSnapshot().state).toBe("unpaired");
  });

  it("ignores unlock when not connected locked", () => {
    connectionStore.onUnlocked();
    expect(connectionStore.getSnapshot().state).toBe("unpaired");
  });
});
