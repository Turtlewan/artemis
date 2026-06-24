import { describe, expect, it } from "vitest";

import { connectionStore } from "../state/connection";

describe("StatusDetail connection actions", () => {
  it("has lock and logout state transitions available to the status screen", () => {
    connectionStore.resetForTest();
    connectionStore.onPaired();
    connectionStore.onConnected();
    connectionStore.onUnlocked();
    connectionStore.onLocked();
    expect(connectionStore.getSnapshot().state).toBe("connectedLocked");
    connectionStore.onRevoked();
    expect(connectionStore.getSnapshot().state).toBe("unpaired");
  });
});
