// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  hide: vi.fn(),
}));

vi.mock("@tauri-apps/api/webviewWindow", () => ({
  getCurrentWebviewWindow: () => ({
    label: "ask",
    hide: mocks.hide,
  }),
}));

vi.mock("../api/gateway", () => ({
  ask: vi.fn(),
}));

import { AskWindow } from "./AskWindow";
import { askStore } from "./askStore";

describe("AskWindow", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    mocks.hide.mockReset();
    askStore.resetForTest();
    window.requestAnimationFrame = (callback: FrameRequestCallback): number => {
      callback(0);
      return 0;
    };
  });

  it("renders AskPopup open and hides the OS ask window on close", () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);

    act(() => root.render(<AskWindow />));
    const close = container.querySelector<HTMLButtonElement>(".ask-close");
    expect(container.querySelector('[role="dialog"]')).not.toBeNull();

    act(() => close?.click());

    expect(mocks.hide).toHaveBeenCalledTimes(1);
  });
});
