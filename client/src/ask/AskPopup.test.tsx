// @vitest-environment jsdom
import { act } from "react";
import type { ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

const eventMocks = vi.hoisted(() => ({
  askSummon: undefined as (() => void) | undefined,
}));

const gatewayMocks = vi.hoisted(() => ({
  askStream: vi.fn(),
  capabilityPropose: vi.fn(),
  capabilityBuild: vi.fn(),
  capabilityPromote: vi.fn(),
}));

const keysMocks = vi.hoisted(() => ({
  openKeys: vi.fn(),
}));

vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn((_event: string, callback: () => void) => {
    eventMocks.askSummon = callback;
    return Promise.resolve(() => {
      eventMocks.askSummon = undefined;
    });
  }),
}));

vi.mock("../api/gateway", () => ({
  askStream: gatewayMocks.askStream,
  capabilityPropose: gatewayMocks.capabilityPropose,
  capabilityBuild: gatewayMocks.capabilityBuild,
  capabilityPromote: gatewayMocks.capabilityPromote,
}));

vi.mock("../settings/keysStore", () => ({
  openKeys: keysMocks.openKeys,
}));

import type { BuildPlanCard } from "../api/dto";
import { connectionStore } from "../state/connection";
import { AskPopup } from "./AskPopup";
import { askStore } from "./askStore";
import { useAskHotkey } from "./useAskHotkey";

const roleSelector = (role: string): string => `[role="${role}"]`;

const getByRole = (
  container: HTMLElement,
  role: string,
  name?: RegExp,
  options?: { pressed?: boolean },
): HTMLElement => {
  const candidates = Array.from(container.querySelectorAll<HTMLElement>(roleSelector(role)));
  if (role === "textbox") {
    candidates.push(...Array.from(container.querySelectorAll<HTMLInputElement>("input")));
  }
  if (role === "button") {
    candidates.push(...Array.from(container.querySelectorAll<HTMLButtonElement>("button")));
  }

  const match = candidates.find((candidate) => {
    if (name === undefined) return true;
    const label = candidate.getAttribute("aria-label");
    const labelledBy = candidate.getAttribute("aria-labelledby");
    const namedBy = labelledBy === null ? "" : (container.querySelector(`#${labelledBy}`)?.textContent ?? "");
    const pressedMatches =
      options?.pressed === undefined ||
      candidate.getAttribute("aria-pressed") === String(options.pressed);
    return pressedMatches && name.test(`${label ?? ""} ${namedBy} ${candidate.textContent ?? ""}`);
  });
  if (match === undefined) throw new Error(`Missing role ${role}`);
  return match;
};

const render = (node: ReactNode): { container: HTMLDivElement; root: Root } => {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  act(() => root.render(node));
  return { container, root };
};

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

function Harness() {
  const ask = useAskHotkey();
  return (
    <>
      <button {...ask.askButtonProps}>Ask</button>
      <AskPopup isOpen={ask.isOpen} onClose={ask.close} />
    </>
  );
}

describe("AskPopup", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    gatewayMocks.askStream.mockReset();
    gatewayMocks.capabilityPropose.mockReset();
    gatewayMocks.capabilityBuild.mockReset();
    gatewayMocks.capabilityPromote.mockReset();
    keysMocks.openKeys.mockReset();
    connectionStore.resetForTest();
    askStore.resetForTest();
    eventMocks.askSummon = undefined;
    window.requestAnimationFrame = (callback: FrameRequestCallback): number => {
      callback(0);
      return 0;
    };
  });

  it("renders the named dialog, textbox, and engine tag text", () => {
    const { container } = render(<AskPopup isOpen={true} onClose={vi.fn()} />);

    expect(getByRole(container, "dialog", /ask artemis/i)).toBeTruthy();
    expect(getByRole(container, "textbox", /ask/i)).toBeTruthy();
    expect(container.textContent).toMatch(/local|codex|review/);
  });

  it("calls the voice trigger when the mic button is pressed", () => {
    const onVoiceTrigger = vi.fn();
    const { container } = render(
      <AskPopup isOpen={true} onClose={vi.fn()} onVoiceTrigger={onVoiceTrigger} />,
    );

    act(() => {
      getByRole(container, "button", /hold to talk/i).click();
    });

    expect(onVoiceTrigger).toHaveBeenCalledWith({ speak: true });
  });

  it("toggles mute with aria-pressed and persists across opens", () => {
    const { container, root } = render(<AskPopup isOpen={true} onClose={vi.fn()} />);
    const toggle = getByRole(container, "button", /speak answers/i, { pressed: false });

    act(() => {
      toggle.click();
    });

    expect(getByRole(container, "button", /muted/i, { pressed: true })).toBeTruthy();

    act(() => root.render(<AskPopup isOpen={false} onClose={vi.fn()} />));
    act(() => root.render(<AskPopup isOpen={true} onClose={vi.fn()} />));

    expect(getByRole(container, "button", /muted/i, { pressed: true })).toBeTruthy();
  });

  it("announces the speaking indicator while speaking", () => {
    askStore.setSpeaking(true);
    const { container } = render(<AskPopup isOpen={true} onClose={vi.fn()} />);

    const indicator = container.querySelector<HTMLElement>('[aria-live="polite"].ask-speaking');
    expect(indicator?.textContent).toContain("Speaking");
  });

  it("focuses the input on open and wraps Tab inside the manual trap", () => {
    const { container } = render(<AskPopup isOpen={true} onClose={vi.fn()} />);
    const input = getByRole(container, "textbox", /ask/i);
    const last = getByRole(container, "button", /send/i);

    expect(document.activeElement).toBe(input);

    act(() => {
      last.focus();
      last.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true }));
    });
    expect(document.activeElement).toBe(input);

    act(() => {
      input.focus();
      input.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true }));
    });
    expect(document.activeElement).toBe(last);
  });

  it("closes on Escape and click-away while restoring previous focus", async () => {
    const before = document.createElement("button");
    before.textContent = "Before";
    document.body.append(before);
    before.focus();
    const { container } = render(<Harness />);

    await act(async () => {
      getByRole(container, "button", /ask/i).click();
    });
    expect(getByRole(container, "dialog", /ask artemis/i)).toBeTruthy();

    await act(async () => {
      getByRole(container, "textbox", /ask/i).dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
      );
    });
    expect(container.querySelector(roleSelector("dialog"))).toBeNull();
    expect(document.activeElement).toBe(before);

    before.focus();
    await act(async () => {
      eventMocks.askSummon?.();
    });
    expect(getByRole(container, "dialog", /ask artemis/i)).toBeTruthy();

    await act(async () => {
      container
        .querySelector<HTMLElement>(".ask-backdrop")
        ?.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    });
    expect(container.querySelector(roleSelector("dialog"))).toBeNull();
    expect(document.activeElement).toBe(before);
  });

  it("renders a plan card and build-mode header chip", async () => {
    connectionStore.onPaired();
    connectionStore.onConnected();
    gatewayMocks.capabilityPropose.mockResolvedValueOnce(planCard());

    await act(async () => {
      await askStore.startBuild("build me a date utility module");
    });
    const { container } = render(<AskPopup isOpen={true} onClose={vi.fn()} />);

    expect(container.textContent).toContain("Building capability");
    expect(container.textContent).toContain("Date Utility");
    expect(container.textContent).toContain("No network access");
    expect(getByRole(container, "button", /build it/i)).toBeTruthy();
  });

  it("renders plan egress domains and flags missing secrets", async () => {
    connectionStore.onPaired();
    connectionStore.onConnected();
    gatewayMocks.capabilityPropose.mockResolvedValueOnce(
      planCard({
        secrets: ["GMAIL_TOKEN", "SLACK_TOKEN"],
        egress_domains: ["gmail.googleapis.com", "oauth2.googleapis.com"],
        missing_secrets: ["GMAIL_TOKEN"],
      }),
    );

    await act(async () => {
      await askStore.startBuild("build me a gmail capability");
    });
    const { container } = render(<AskPopup isOpen={true} onClose={vi.fn()} />);

    expect(container.textContent).toContain("Network access");
    expect(container.textContent).toContain("gmail.googleapis.com");
    expect(container.textContent).toContain("oauth2.googleapis.com");
    expect(container.textContent).toContain("GMAIL_TOKEN (missing)");
    expect(container.textContent).toContain("SLACK_TOKEN");
    expect(container.textContent).toContain("Missing secrets: GMAIL_TOKEN");
  });

  it("shows pending credentials after a passing build and deep-links each key", async () => {
    connectionStore.onPaired();
    connectionStore.onConnected();
    gatewayMocks.capabilityPropose.mockResolvedValueOnce(
      planCard({
        secrets: ["GMAIL_TOKEN"],
        egress_domains: ["gmail.googleapis.com"],
        missing_secrets: ["GMAIL_TOKEN"],
      }),
    );
    gatewayMocks.capabilityBuild.mockImplementationOnce(async function* () {
      yield { type: "build_result", build_id: "build-1", passed: true, blocked: false, output: "ok" };
      yield { type: "done" };
    });

    await act(async () => {
      await askStore.startBuild("build me a gmail capability");
      await askStore.confirmBuild("build-1");
    });
    const { container } = render(<AskPopup isOpen={true} onClose={vi.fn()} />);

    expect(container.textContent).toContain("Pending credentials");
    expect(container.textContent).toContain("Add these keys when you are ready");
    expect(getByRole(container, "button", /add to my capabilities/i)).toBeTruthy();

    const addKey = container.querySelector<HTMLButtonElement>(
      'button[aria-label="Add key GMAIL_TOKEN"]',
    );
    expect(addKey).toBeTruthy();

    act(() => {
      addKey?.click();
    });

    expect(keysMocks.openKeys).toHaveBeenCalledWith("GMAIL_TOKEN");
  });

  it("does not show pending credentials when no secrets are missing", async () => {
    connectionStore.onPaired();
    connectionStore.onConnected();
    gatewayMocks.capabilityPropose.mockResolvedValueOnce(
      planCard({
        secrets: ["GMAIL_TOKEN"],
        egress_domains: ["gmail.googleapis.com"],
        missing_secrets: [],
      }),
    );
    gatewayMocks.capabilityBuild.mockImplementationOnce(async function* () {
      yield { type: "build_result", build_id: "build-1", passed: true, blocked: false, output: "ok" };
      yield { type: "done" };
    });

    await act(async () => {
      await askStore.startBuild("build me a gmail capability");
      await askStore.confirmBuild("build-1");
    });
    const { container } = render(<AskPopup isOpen={true} onClose={vi.fn()} />);

    expect(container.textContent).not.toContain("Pending credentials");
    expect(container.querySelector('button[aria-label^="Add key"]')).toBeNull();
  });

  it("wires Adjust to cancelBuild with the plan message id and removes the plan card", async () => {
    connectionStore.onPaired();
    connectionStore.onConnected();
    gatewayMocks.capabilityPropose.mockResolvedValueOnce(planCard());
    await act(async () => {
      await askStore.startBuild("build me a date utility module");
    });
    const planMessageId = askStore.getSnapshot().messages.find((message) => message.kind === "plan")?.id;
    expect(planMessageId).toBeDefined();
    const cancelBuild = vi.spyOn(askStore, "cancelBuild");
    const { container } = render(<AskPopup isOpen={true} onClose={vi.fn()} />);

    act(() => {
      getByRole(container, "button", /adjust/i).click();
    });

    expect(cancelBuild).toHaveBeenCalledWith(planMessageId);
    expect(container.textContent).not.toContain("Date Utility");
    expect(container.textContent).not.toContain("Building capability");
    expect(document.activeElement).toBe(getByRole(container, "textbox", /ask/i));
    cancelBuild.mockRestore();
  });

  it("wires Build it to confirmBuild with the plan build id", async () => {
    connectionStore.onPaired();
    connectionStore.onConnected();
    gatewayMocks.capabilityPropose.mockResolvedValueOnce(planCard());
    await act(async () => {
      await askStore.startBuild("build me a date utility module");
    });
    const confirmBuild = vi.spyOn(askStore, "confirmBuild").mockResolvedValueOnce(undefined);
    const { container } = render(<AskPopup isOpen={true} onClose={vi.fn()} />);

    act(() => {
      getByRole(container, "button", /build it/i).click();
    });

    expect(confirmBuild).toHaveBeenCalledWith("build-1");
    confirmBuild.mockRestore();
  });

  it("renders a blocked plan reason and disables Build it", async () => {
    connectionStore.onPaired();
    connectionStore.onConnected();
    gatewayMocks.capabilityPropose.mockResolvedValueOnce(
      planCard({ blocked: true, block_reason: "Requires a network secret." }),
    );

    await act(async () => {
      await askStore.startBuild("build me a calendar capability");
    });
    const { container } = render(<AskPopup isOpen={true} onClose={vi.fn()} />);
    const buildButton = getByRole(container, "button", /build it/i) as HTMLButtonElement;

    expect(container.textContent).toContain("Requires a network secret.");
    expect(buildButton.disabled).toBe(true);
  });
});
