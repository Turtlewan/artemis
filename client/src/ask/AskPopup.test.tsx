// @vitest-environment jsdom
import { act } from "react";
import type { ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

const eventMocks = vi.hoisted(() => ({
  askSummon: undefined as (() => void) | undefined,
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
  askStream: vi.fn(),
}));

import { AskPopup } from "./AskPopup";
import { askStore } from "./askStore";
import { useAskHotkey } from "./useAskHotkey";

const roleSelector = (role: string): string => `[role="${role}"]`;

const getByRole = (container: HTMLElement, role: string, name?: RegExp): HTMLElement => {
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
    return name.test(`${label ?? ""} ${namedBy} ${candidate.textContent ?? ""}`);
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

  it("focuses the input on open and wraps Tab inside the manual trap", () => {
    const { container } = render(<AskPopup isOpen={true} onClose={vi.fn()} />);
    const input = getByRole(container, "textbox", /ask/i);
    const row = container.querySelector<HTMLElement>(".ask-result-row");

    expect(document.activeElement).toBe(input);

    act(() => {
      row?.focus();
      row?.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true }));
    });
    expect(document.activeElement).toBe(input);

    act(() => {
      input.focus();
      input.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true }));
    });
    expect(document.activeElement).toBe(row);
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
});
