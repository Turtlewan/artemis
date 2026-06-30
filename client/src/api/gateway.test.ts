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

import { layoutStore } from "../state/layout";
import * as gateway from "./gateway";

describe("gateway facade", () => {
  beforeEach(() => {
    mocks.invoke.mockReset();
    layoutStore.resetForTest();
  });

  it("invokes app_status and returns the status DTO", async () => {
    const dto = { connected: true, vault_unlocked: false, device_id: "dev-1" };
    mocks.invoke.mockResolvedValueOnce(dto);

    await expect(gateway.status()).resolves.toEqual(dto);
    expect(mocks.invoke).toHaveBeenCalledWith("app_status", undefined);
  });

  it("passes app_ask request args through invoke", async () => {
    const response = { text: "answer", path: "direct", tool_used: null, escalated: false };
    mocks.invoke.mockResolvedValueOnce(response);

    await expect(gateway.ask({ text: "hello" })).resolves.toEqual(response);
    expect(mocks.invoke).toHaveBeenCalledWith("app_ask", { request: { text: "hello" } });
  });

  it("maps rejected invoke status errors", async () => {
    mocks.invoke.mockRejectedValueOnce({ status: 401 });
    await expect(gateway.status()).rejects.toEqual({ kind: "unauthenticated" });

    mocks.invoke.mockRejectedValueOnce({ status: 423 });
    await expect(gateway.status()).rejects.toEqual({ kind: "vaultLocked" });
  });

  it("round-trips layout through invoke", async () => {
    const layout = {
      version: 1,
      updated_at: "2026-06-24T00:00:00.000Z",
      cards: [],
    };
    mocks.invoke.mockResolvedValueOnce(layout);

    await expect(gateway.layoutPut(layout)).resolves.toEqual(layout);
    expect(mocks.invoke).toHaveBeenCalledWith("app_layout_put", { layout });
  });

  it("routes task suggestion accept and reject through owner commands", async () => {
    mocks.invoke.mockResolvedValueOnce({ task: { id: "task-1", due_at: "2026-07-02" } });

    await expect(gateway.acceptSuggestion("sug-1", "2026-07-02")).resolves.toEqual({
      task: { id: "task-1", due_at: "2026-07-02" },
    });
    expect(mocks.invoke).toHaveBeenCalledWith("task_suggestion_accept", {
      suggestionId: "sug-1",
      dueAt: "2026-07-02",
    });

    mocks.invoke.mockResolvedValueOnce({ ok: true });

    await expect(gateway.rejectSuggestion("sug-1")).resolves.toEqual({ ok: true });
    expect(mocks.invoke).toHaveBeenCalledWith("task_suggestion_reject", {
      suggestionId: "sug-1",
    });
  });

  it("invokes app_capability_propose with the goal and returns the plan card", async () => {
    const card = {
      build_id: "b",
      name: "Planner",
      description: "Plan things",
      summary: "Adds planning",
      secrets: ["TOKEN"],
      blocked: false,
      block_reason: null,
    };
    mocks.invoke.mockResolvedValueOnce(card);

    await expect(gateway.capabilityPropose("Build a planner…")).resolves.toEqual(card);
    expect(mocks.invoke).toHaveBeenCalledWith("app_capability_propose", {
      goal: "Build a planner…",
    });
  });

  it("invokes app_capability_promote with the build id", async () => {
    const installed = { name: "Planner", version: 1, path: "/capabilities/planner" };
    mocks.invoke.mockResolvedValueOnce(installed);

    await expect(gateway.capabilityPromote("b")).resolves.toEqual(installed);
    expect(mocks.invoke).toHaveBeenCalledWith("app_capability_promote", { buildId: "b" });
  });

  it("streams capability build events until done", async () => {
    mocks.invoke.mockImplementationOnce((_command: string, args?: Record<string, unknown>) => {
      const channel = args?.channel as { onmessage: ((event: unknown) => void) | null };
      channel.onmessage?.({ type: "build_status", text: "Testing in sandbox…" });
      channel.onmessage?.({
        type: "build_result",
        build_id: "b",
        passed: true,
        blocked: false,
        output: "ok",
      });
      channel.onmessage?.({ type: "done" });
      return Promise.resolve();
    });

    const events = [];
    for await (const event of gateway.capabilityBuild("b")) {
      events.push(event);
    }

    expect(mocks.invoke).toHaveBeenCalledWith("app_capability_build", {
      buildId: "b",
      channel: expect.any(Object),
    });
    expect(events).toEqual([
      { type: "build_status", text: "Testing in sandbox…" },
      {
        type: "build_result",
        build_id: "b",
        passed: true,
        blocked: false,
        output: "ok",
      },
      { type: "done" },
    ]);
  });

  it("layout store discards stale PUT responses by updated_at", async () => {
    const newer = {
      version: 1,
      updated_at: "2026-06-24T01:00:00.000Z",
      cards: [{ id: "email", domain: "email", cluster: "Comms", x: 1, y: 2, w: 3, h: 4 }],
    };
    const older = {
      version: 1,
      updated_at: "2026-06-24T00:00:00.000Z",
      cards: [],
    };
    mocks.invoke.mockResolvedValueOnce(older);
    layoutStore.setLocalLayout(newer);

    await layoutStore.flush(newer);

    expect(layoutStore.getSnapshot().layout).toEqual(newer);
    expect(mocks.invoke).toHaveBeenCalledWith("app_layout_put", { layout: newer });
  });
});
