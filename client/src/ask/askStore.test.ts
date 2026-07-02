import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  ask: vi.fn(),
  askStream: vi.fn(),
  invokeConfirm: vi.fn(),
  capabilityPropose: vi.fn(),
  capabilityBuild: vi.fn(),
  capabilityPromote: vi.fn(),
}));

vi.mock("../api/gateway", () => ({
  ask: mocks.ask,
  askStream: mocks.askStream,
  invokeConfirm: mocks.invokeConfirm,
  capabilityPropose: mocks.capabilityPropose,
  capabilityBuild: mocks.capabilityBuild,
  capabilityPromote: mocks.capabilityPromote,
}));

import type { BuildPlanCard, InstalledCard } from "../api/dto";
import { connectionStore } from "../state/connection";
import { askStore } from "./askStore";

const planCard = (patch: Partial<BuildPlanCard> = {}): BuildPlanCard => ({
  build_id: "build-1",
  name: "Date Utility",
  description: "Creates a local date helper.",
  summary: "Add a date utility module.",
  secrets: [],
  egress_domains: [],
  missing_secrets: [],
  blocked: false,
  block_reason: null,
  ...patch,
});

const installedCard = (patch: Partial<InstalledCard> = {}): InstalledCard => ({
  name: "Date Utility",
  version: 1,
  path: "capabilities/date-utility",
  ...patch,
});

describe("askStore", () => {
  beforeEach(() => {
    mocks.ask.mockReset();
    mocks.askStream.mockReset();
    mocks.invokeConfirm.mockReset();
    mocks.capabilityPropose.mockReset();
    mocks.capabilityBuild.mockReset();
    mocks.capabilityPromote.mockReset();
    connectionStore.resetForTest();
    askStore.resetForTest();
  });

  it("adds one assistant message and finalizes engine metadata from ask", async () => {
    connectionStore.onPaired();
    connectionStore.onConnected();
    mocks.ask.mockResolvedValueOnce({
      text: "Hello there.",
      path: "cloud",
      tool_used: undefined,
      escalated: false,
    });

    await askStore.send("status");

    const snapshot = askStore.getSnapshot();
    expect(mocks.ask).toHaveBeenCalledWith({ text: "status", speak: true });
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
    mocks.ask.mockResolvedValueOnce({
      text: "",
      path: "local",
      tool_used: undefined,
      escalated: false,
    });

    expect(askStore.getSnapshot().muted).toBe(false);
    askStore.toggleMute();
    expect(askStore.getSnapshot().muted).toBe(true);

    await askStore.send("quiet");

    expect(mocks.ask).toHaveBeenCalledWith({ text: "quiet", speak: false });
    expect(askStore.getSnapshot().muted).toBe(true);
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

  it("marks a vault lock as failed and assertive without finalizing", async () => {
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
    expect(askStore.getSnapshot().engineStatus.codex).toBe(false);
  });

  it("routes build intent to capability propose and appends a plan message", async () => {
    connectionStore.onPaired();
    connectionStore.onConnected();
    mocks.capabilityPropose.mockResolvedValueOnce(planCard());

    await askStore.send("build me a date utility module");

    const snapshot = askStore.getSnapshot();
    expect(mocks.capabilityPropose).toHaveBeenCalledWith("build me a date utility module");
    expect(mocks.ask).not.toHaveBeenCalled();
    expect(snapshot.buildMode).toBe(true);
    expect(snapshot.messages).toMatchObject([
      { role: "user", text: "build me a date utility module" },
      { role: "assistant", kind: "plan", buildId: "build-1", plan: { name: "Date Utility" } },
    ]);
  });

  it("cancelBuild removes the dismissed message and clears build mode", async () => {
    connectionStore.onPaired();
    connectionStore.onConnected();
    mocks.capabilityPropose.mockResolvedValueOnce(planCard());

    await askStore.startBuild("build a date utility module");
    const planMessageId = askStore.getSnapshot().messages.find((message) => message.kind === "plan")?.id;
    expect(planMessageId).toBeDefined();

    askStore.cancelBuild(planMessageId!);

    const snapshot = askStore.getSnapshot();
    expect(snapshot.buildMode).toBe(false);
    expect(snapshot.messages.some((message) => message.id === planMessageId)).toBe(false);
    expect(snapshot.messages).toMatchObject([{ role: "user", text: "build a date utility module" }]);
  });

  it("keeps normal non-build messages on ask", async () => {
    connectionStore.onPaired();
    connectionStore.onConnected();
    mocks.ask.mockResolvedValueOnce({
      text: "Normal answer.",
      path: "local",
      tool_used: undefined,
      escalated: false,
    });

    await askStore.send("what is my status");

    expect(mocks.ask).toHaveBeenCalledWith({ text: "what is my status", speak: true });
    expect(mocks.capabilityPropose).not.toHaveBeenCalled();
  });

  it("adds an invoke confirm card from an invoke_confirm response", async () => {
    connectionStore.onPaired();
    connectionStore.onConnected();
    mocks.ask.mockResolvedValueOnce({
      text: "",
      path: "invoke_confirm",
      tool_used: undefined,
      escalated: false,
      invoke_id: "inv-1",
      capability: "gmail.send",
      egress_domains: ["gmail.googleapis.com"],
      secrets: ["GMAIL_TOKEN"],
      args: { to: "owner@example.com" },
    });

    await askStore.send("send the email");

    const card = askStore.getSnapshot().messages.find((message) => message.kind === "invoke_confirm");
    expect(card).toMatchObject({
      role: "assistant",
      text: "",
      kind: "invoke_confirm",
      invoke: {
        invokeId: "inv-1",
        capability: "gmail.send",
        egressDomains: ["gmail.googleapis.com"],
        secrets: ["GMAIL_TOKEN"],
        args: { to: "owner@example.com" },
        missingSecrets: [],
      },
    });
  });

  it("adds a plain clarify message from an invoke_clarify response", async () => {
    connectionStore.onPaired();
    connectionStore.onConnected();
    mocks.ask.mockResolvedValueOnce({
      text: "ignored",
      path: "invoke_clarify",
      tool_used: undefined,
      escalated: false,
      capability: "gmail.send",
      missing: ["recipient", "body"],
    });

    await askStore.send("send it");

    const snapshot = askStore.getSnapshot();
    expect(snapshot.messages.some((message) => message.kind === "invoke_confirm")).toBe(false);
    expect(snapshot.messages[snapshot.messages.length - 1]).toMatchObject({
      role: "assistant",
      text: "I need more detail to run 'gmail.send': recipient, body",
    });
  });

  it("confirmInvoke replaces an ok card with plain result text", async () => {
    connectionStore.onPaired();
    connectionStore.onConnected();
    mocks.ask.mockResolvedValueOnce({
      text: "",
      path: "invoke_confirm",
      escalated: false,
      invoke_id: "inv-1",
      capability: "gmail.send",
    });
    mocks.invokeConfirm.mockResolvedValueOnce({
      status: "ok",
      text: "Ran it.",
      invoke_id: "inv-1",
      missing_secrets: [],
    });

    await askStore.send("send it");
    const messageId = askStore.getSnapshot().messages.find((message) => message.kind === "invoke_confirm")?.id;
    await askStore.confirmInvoke(messageId!);

    expect(mocks.invokeConfirm).toHaveBeenCalledWith("inv-1");
    expect(askStore.getSnapshot().messages.find((message) => message.id === messageId)).toMatchObject({
      role: "assistant",
      text: "Ran it.",
    });
    expect(askStore.getSnapshot().messages.find((message) => message.id === messageId)?.kind).toBeUndefined();
  });

  it("confirmInvoke keeps the card and records missing secrets", async () => {
    connectionStore.onPaired();
    connectionStore.onConnected();
    mocks.ask.mockResolvedValueOnce({
      text: "",
      path: "invoke_confirm",
      escalated: false,
      invoke_id: "inv-1",
      capability: "gmail.send",
    });
    mocks.invokeConfirm.mockResolvedValueOnce({
      status: "missing_secrets",
      text: null,
      invoke_id: "inv-1",
      missing_secrets: ["TAVILY_API_KEY"],
    });

    await askStore.send("search");
    const messageId = askStore.getSnapshot().messages.find((message) => message.kind === "invoke_confirm")?.id;
    await askStore.confirmInvoke(messageId!);

    expect(askStore.getSnapshot().messages.find((message) => message.id === messageId)).toMatchObject({
      kind: "invoke_confirm",
      invoke: { missingSecrets: ["TAVILY_API_KEY"] },
    });
  });

  it("confirmInvoke replaces not_found and error responses with plain error text", async () => {
    connectionStore.onPaired();
    connectionStore.onConnected();
    mocks.ask
      .mockResolvedValueOnce({
        text: "",
        path: "invoke_confirm",
        escalated: false,
        invoke_id: "inv-1",
        capability: "gmail.send",
      })
      .mockResolvedValueOnce({
        text: "",
        path: "invoke_confirm",
        escalated: false,
        invoke_id: "inv-2",
        capability: "gmail.send",
      });
    mocks.invokeConfirm
      .mockResolvedValueOnce({
        status: "not_found",
        text: null,
        invoke_id: "inv-1",
        missing_secrets: [],
      })
      .mockResolvedValueOnce({
        status: "error",
        text: null,
        invoke_id: "inv-2",
        missing_secrets: [],
      });

    await askStore.send("send it");
    const expiredId = askStore.getSnapshot().messages.find((message) => message.kind === "invoke_confirm")?.id;
    await askStore.confirmInvoke(expiredId!);
    await askStore.send("send it again");
    const errorId = askStore.getSnapshot().messages.find((message) => message.kind === "invoke_confirm")?.id;
    await askStore.confirmInvoke(errorId!);

    expect(askStore.getSnapshot().messages.find((message) => message.id === expiredId)).toMatchObject({
      text: "That request has expired — ask again.",
    });
    expect(askStore.getSnapshot().messages.find((message) => message.id === errorId)).toMatchObject({
      text: "Something went wrong running that.",
    });
  });

  it("cancelInvoke removes the confirm card message", async () => {
    connectionStore.onPaired();
    connectionStore.onConnected();
    mocks.ask.mockResolvedValueOnce({
      text: "",
      path: "invoke_confirm",
      escalated: false,
      invoke_id: "inv-1",
      capability: "gmail.send",
    });

    await askStore.send("send it");
    const messageId = askStore.getSnapshot().messages.find((message) => message.kind === "invoke_confirm")?.id;
    expect(messageId).toBeDefined();

    askStore.cancelInvoke(messageId!);

    expect(askStore.getSnapshot().messages.some((message) => message.id === messageId)).toBe(false);
  });

  it("confirmBuild streams status and appends a passing result message", async () => {
    mocks.capabilityBuild.mockImplementationOnce(async function* () {
      yield { type: "build_status", text: "Running checks" };
      yield { type: "build_result", build_id: "build-1", passed: true, blocked: false, output: "ok" };
      yield { type: "done" };
    });

    await askStore.confirmBuild("build-1");

    const snapshot = askStore.getSnapshot();
    expect(mocks.capabilityBuild).toHaveBeenCalledWith("build-1");
    expect(snapshot.messages).toMatchObject([
      { role: "assistant", kind: "status", text: "Running checks", buildId: "build-1" },
      {
        role: "assistant",
        kind: "result",
        buildId: "build-1",
        result: { passed: true, blocked: false, output: "ok" },
      },
    ]);
  });

  it("promoteBuild appends installed confirmation and clears build mode", async () => {
    connectionStore.onPaired();
    connectionStore.onConnected();
    mocks.capabilityPropose.mockResolvedValueOnce(planCard());
    mocks.capabilityPromote.mockResolvedValueOnce(installedCard());

    await askStore.startBuild("build a date utility module");
    await askStore.promoteBuild("build-1");

    const snapshot = askStore.getSnapshot();
    expect(mocks.capabilityPromote).toHaveBeenCalledWith("build-1");
    expect(snapshot.buildMode).toBe(false);
    expect(snapshot.messages[snapshot.messages.length - 1]).toMatchObject({
      role: "assistant",
      kind: "installed",
      text: `Added "Date Utility" (v1) — built & verified.`,
    });
    expect(snapshot.messages[snapshot.messages.length - 1]?.text).toContain("built & verified");
    expect(snapshot.messages[snapshot.messages.length - 1]?.text).not.toContain("map");
  });

  it("appends blocked plan messages from capability propose", async () => {
    connectionStore.onPaired();
    connectionStore.onConnected();
    mocks.capabilityPropose.mockResolvedValueOnce(
      planCard({ blocked: true, block_reason: "Requires a network secret." }),
    );

    await askStore.send("build me a calendar capability");

    const plan = askStore.getSnapshot().messages.find((message) => message.kind === "plan");
    expect(plan).toMatchObject({
      kind: "plan",
      plan: { blocked: true, block_reason: "Requires a network secret." },
    });
  });
});
