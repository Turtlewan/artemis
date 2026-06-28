import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  invoke: vi.fn(),
}));

vi.mock("@tauri-apps/api/core", () => ({
  invoke: mocks.invoke,
  Channel: class<T> {
    onmessage: ((event: T) => void) | null = null;
  },
}));

import * as gateway from "./gateway";

describe("voice gateway facade", () => {
  beforeEach(() => {
    mocks.invoke.mockReset();
  });

  it("streams voice ask events through the app_ask_voice command", async () => {
    mocks.invoke.mockImplementationOnce(
      async (_command: string, args: { channel: { onmessage: (event: unknown) => void } }) => {
        args.channel.onmessage({ type: "text", text: "hello" });
        args.channel.onmessage({ type: "done", path: null, tool_used: null, escalated: false });
      },
    );

    const events = [];
    for await (const event of gateway.askVoice(true)) {
      events.push(event);
    }

    expect(mocks.invoke).toHaveBeenCalledWith("app_ask_voice", {
      speak: true,
      channel: expect.any(Object),
    });
    expect(events).toEqual([
      { type: "text", text: "hello" },
      { type: "done", path: null, tool_used: null, escalated: false },
    ]);
  });
});
