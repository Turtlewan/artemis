// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

type CapturedAskPopupProps = {
  onVoiceTrigger?: (options: { speak: boolean }) => void | Promise<void>;
};

const mocks = vi.hoisted(() => ({
  askPopupProps: undefined as CapturedAskPopupProps | undefined,
  askVoice: vi.fn(),
}));

vi.mock("../ask/AskPopup", () => ({
  AskPopup: (props: CapturedAskPopupProps) => {
    mocks.askPopupProps = props;
    return null;
  },
}));

vi.mock("../api/gateway", () => ({
  askVoice: mocks.askVoice,
}));

import App from "../App";
import { connectionStore } from "../state/connection";

describe("App voice Ask wiring", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    window.requestAnimationFrame = (callback: FrameRequestCallback): number => {
      callback(0);
      return 0;
    };
    window.matchMedia = vi.fn((query: string) => ({
      matches: query === "(prefers-reduced-motion: reduce)",
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
  });

  it("passes a voice trigger to AskPopup that calls askVoice with the speak flag", async () => {
    connectionStore.resetForTest();
    connectionStore.onPaired();
    connectionStore.onConnected();
    mocks.askPopupProps = undefined;
    mocks.askVoice.mockImplementationOnce(async function* (_speak: boolean) {});

    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    act(() => root.render(<App />));

    const props = mocks.askPopupProps as unknown as CapturedAskPopupProps;
    expect(props.onVoiceTrigger).toBeDefined();
    await props.onVoiceTrigger?.({ speak: false });
    expect(mocks.askVoice).toHaveBeenCalledWith(false);
  });
});
