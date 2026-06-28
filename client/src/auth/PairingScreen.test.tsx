// @vitest-environment jsdom
import { invoke } from "@tauri-apps/api/core";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import App from "../App";
import { connectionStore } from "../state/connection";
import { PairingScreen } from "./PairingScreen";

vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn(),
}));

vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn(() => Promise.resolve(() => undefined)),
}));

const mockedInvoke = vi.mocked(invoke);
const mountedRoots: Root[] = [];
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const render = (node: ReactNode): { container: HTMLDivElement; root: Root } => {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  mountedRoots.push(root);
  act(() => root.render(node));
  return { container, root };
};

const textOf = (element: Element | null): string => element?.textContent?.trim() ?? "";

const getByLabelText = (container: HTMLElement, text: RegExp): HTMLInputElement => {
  const labels = Array.from(container.querySelectorAll("label"));
  const label = labels.find((candidate) => text.test(textOf(candidate)));
  const input = label?.querySelector("input");
  if (input === undefined || input === null) throw new Error(`Missing input label ${text}`);
  return input;
};

const getButton = (container: HTMLElement, text: RegExp): HTMLButtonElement => {
  const button = Array.from(container.querySelectorAll("button")).find((candidate) =>
    text.test(textOf(candidate)),
  );
  if (button === undefined) throw new Error(`Missing button ${text}`);
  return button;
};

const changeInput = (input: HTMLInputElement, value: string): void => {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  setter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
};

const waitFor = async (assertion: () => void): Promise<void> => {
  const deadline = Date.now() + 1_000;
  let lastError: unknown;
  while (Date.now() < deadline) {
    try {
      assertion();
      return;
    } catch (error: unknown) {
      lastError = error;
      await new Promise((resolve) => window.setTimeout(resolve, 10));
    }
  }
  throw lastError;
};

describe("PairingScreen", () => {
  beforeEach(() => {
    for (const root of mountedRoots.splice(0)) {
      act(() => root.unmount());
    }
    document.body.innerHTML = "";
    connectionStore.resetForTest();
    mockedInvoke.mockReset();
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

  afterEach(() => {
    for (const root of mountedRoots.splice(0)) {
      act(() => root.unmount());
    }
  });

  test("renders the gateway in unpaired", () => {
    const { container } = render(<PairingScreen state="unpaired" />);

    expect(getByLabelText(container, /pairing code/i)).toBeTruthy();
    expect(getButton(container, /^pair$/i)).toBeTruthy();
  });

  test("submit calls pairDevice and drives the store", async () => {
    mockedInvoke.mockResolvedValue({});
    const { container } = render(<PairingScreen state="unpaired" />);

    await act(async () => {
      changeInput(getByLabelText(container, /pairing code/i), "abc-123");
    });
    await act(async () => {
      container.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });

    expect(mockedInvoke).toHaveBeenNthCalledWith(1, "auth_pair", { pairingCode: "abc-123" });
    expect(mockedInvoke).toHaveBeenNthCalledWith(2, "auth_connect");
    expect(mockedInvoke).toHaveBeenNthCalledWith(3, "auth_unlock");
    expect(connectionStore.getSnapshot().state).toBe("unlocked");
  });

  test.each([
    [
      { kind: "pairingRejected" },
      "That code didn't work or has expired. Mint a new one and try again.",
    ],
    [{ kind: "network" }, "Can't reach your brain. Check the tunnel/connection."],
    [{ kind: "biometricCancelled" }, "Biometric check was cancelled. Try again."],
    [{ kind: "vaultLocked" }, "Something went wrong reaching your brain. Try again."],
  ])("maps PairingError to the alert region", async (thrown, message) => {
    mockedInvoke.mockRejectedValueOnce(thrown);
    const { container } = render(<PairingScreen state="unpaired" />);
    const input = getByLabelText(container, /pairing code/i);

    await act(async () => {
      changeInput(input, "expired-code");
    });
    await act(async () => {
      container.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });

    expect(textOf(container.querySelector('[role="alert"]'))).toBe(message);
    expect(input.disabled).toBe(false);
    expect(getButton(container, /^pair$/i).disabled).toBe(false);
    expect(connectionStore.getSnapshot().state).toBe("unpaired");
  });

  test("connecting state disables the form", async () => {
    let resolvePair: (value: unknown) => void = () => undefined;
    const pendingPair = new Promise((resolve) => {
      resolvePair = resolve;
    });
    mockedInvoke.mockImplementation((command) =>
      command === "auth_pair" ? pendingPair : Promise.resolve({}),
    );
    const { container } = render(<PairingScreen state="unpaired" />);
    const input = getByLabelText(container, /pairing code/i);

    await act(async () => {
      changeInput(input, "pending-code");
    });
    await act(async () => {
      container.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(input.disabled).toBe(true);
      const button = getButton(container, /^connecting…$/i);
      expect(button.disabled).toBe(true);
    });

    resolvePair({});
    await act(async () => {
      await pendingPair;
      await Promise.resolve();
    });
    expect(connectionStore.getSnapshot().state).toBe("unlocked");
  });

  test("recovery sub-field invokes recovery and clears the passphrase", async () => {
    mockedInvoke.mockResolvedValue({});
    const { container } = render(<PairingScreen state="unpaired" />);

    await act(async () => {
      getButton(container, /recover with passphrase/i).click();
    });
    expect(getButton(container, /recover with passphrase/i).getAttribute("aria-expanded")).toBe("true");

    const input = getByLabelText(container, /recovery passphrase/i);
    await act(async () => {
      changeInput(input, "secret recovery");
    });
    await act(async () => {
      getButton(container, /^recover$/i).click();
    });

    expect(mockedInvoke).toHaveBeenCalledWith("auth_recover", { passphrase: "secret recovery" });
    expect(input.value).toBe("");
  });

  test("App mounts the pairing code input while unpaired", () => {
    const { container } = render(<App />);

    expect(getByLabelText(container, /pairing code/i)).toBeTruthy();
  });
});
