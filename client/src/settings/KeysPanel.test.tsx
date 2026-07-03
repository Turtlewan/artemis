// @vitest-environment jsdom
import { act } from "react";
import type { ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

const gatewayMocks = vi.hoisted(() => ({
  secretSet: vi.fn(),
  secretList: vi.fn(),
  secretDelete: vi.fn(),
  blessList: vi.fn(),
  blessClear: vi.fn(),
}));

vi.mock("../api/gateway", () => ({
  secretSet: gatewayMocks.secretSet,
  secretList: gatewayMocks.secretList,
  secretDelete: gatewayMocks.secretDelete,
}));

vi.mock("../api/bless", () => ({
  blessList: gatewayMocks.blessList,
  blessClear: gatewayMocks.blessClear,
}));

import { KeysPanel } from "./KeysPanel";

const render = (node: ReactNode): { container: HTMLDivElement; root: Root } => {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  act(() => root.render(node));
  return { container, root };
};

const flush = async (): Promise<void> => {
  await act(async () => {
    await Promise.resolve();
  });
};

const byLabel = <T extends HTMLElement>(container: HTMLElement, label: RegExp): T => {
  const labelled = Array.from(container.querySelectorAll<HTMLElement>("[aria-label]")).find(
    (candidate) => label.test(candidate.getAttribute("aria-label") ?? ""),
  );
  if (labelled !== undefined) return labelled as T;

  const labelNode = Array.from(container.querySelectorAll<HTMLLabelElement>("label")).find(
    (candidate) => label.test(candidate.textContent ?? ""),
  );
  const control = labelNode?.querySelector<HTMLElement>("input,button");
  if (control !== undefined) return control as T;

  throw new Error(`Missing label ${label}`);
};

const inputByName = (container: HTMLElement, name: string): HTMLInputElement => {
  const input = container.querySelector<HTMLInputElement>(`input[name="${name}"]`);
  if (input === null) throw new Error(`Missing input ${name}`);
  return input;
};

const buttonByText = (container: HTMLElement, text: RegExp): HTMLButtonElement => {
  const match = Array.from(container.querySelectorAll<HTMLButtonElement>("button")).find(
    (button) => text.test(button.textContent ?? ""),
  );
  if (match === undefined) throw new Error(`Missing button ${text}`);
  return match;
};

const changeInput = (input: HTMLInputElement, value: string): void => {
  // Use the native value setter so React's controlled-input valueTracker registers the change
  // (assigning `.value` directly is skipped by React and onChange never fires).
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  setter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
};

describe("KeysPanel", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    gatewayMocks.secretSet.mockReset();
    gatewayMocks.secretList.mockReset();
    gatewayMocks.secretDelete.mockReset();
    gatewayMocks.blessList.mockReset();
    gatewayMocks.blessClear.mockReset();
    gatewayMocks.blessList.mockResolvedValue([]);
  });

  it("renders secret names without rendering values", async () => {
    gatewayMocks.secretList.mockResolvedValueOnce(["OPENAI_API_KEY", "GITHUB_TOKEN"]);
    const secretValue = "sk-secret-value";

    const { container } = render(<KeysPanel open={true} onClose={vi.fn()} />);
    await flush();

    expect(container.textContent).toContain("OPENAI_API_KEY");
    expect(container.textContent).toContain("GITHUB_TOKEN");
    expect(container.textContent).not.toContain(secretValue);
  });

  it("adds a secret and refreshes the names list", async () => {
    gatewayMocks.secretList.mockResolvedValueOnce([]).mockResolvedValueOnce(["NEW_KEY"]);
    gatewayMocks.secretSet.mockResolvedValueOnce(undefined);
    const { container } = render(<KeysPanel open={true} onClose={vi.fn()} />);
    await flush();

    act(() => {
      changeInput(inputByName(container, "secret-name"), "NEW_KEY");
      changeInput(inputByName(container, "secret-value"), "hidden-value");
    });
    await act(async () => {
      buttonByText(container, /^add$/i).click();
      await Promise.resolve();
    });
    await flush();

    expect(gatewayMocks.secretSet).toHaveBeenCalledWith("NEW_KEY", "hidden-value");
    expect(gatewayMocks.secretList).toHaveBeenCalledTimes(2);
    expect(container.textContent).toContain("NEW_KEY");
    expect(container.textContent).not.toContain("hidden-value");
  });

  it("deletes a secret and refreshes the names list", async () => {
    gatewayMocks.secretList.mockResolvedValueOnce(["DELETE_ME"]).mockResolvedValueOnce([]);
    gatewayMocks.secretDelete.mockResolvedValueOnce(undefined);
    const { container } = render(<KeysPanel open={true} onClose={vi.fn()} />);
    await flush();

    await act(async () => {
      byLabel<HTMLButtonElement>(container, /delete delete_me/i).click();
      await Promise.resolve();
    });
    await flush();

    expect(gatewayMocks.secretDelete).toHaveBeenCalledWith("DELETE_ME");
    expect(gatewayMocks.secretList).toHaveBeenCalledTimes(2);
    expect(container.textContent).not.toContain("DELETE_ME");
  });

  it("revokes a Telegram-blessed capability and refreshes the list", async () => {
    gatewayMocks.secretList.mockResolvedValue([]);
    gatewayMocks.blessList
      .mockResolvedValueOnce([
        { name: "Echo", current_version: 2, blessed_version: 2, blessed: true },
      ])
      .mockResolvedValueOnce([]);
    gatewayMocks.blessClear.mockResolvedValueOnce(undefined);
    const { container } = render(<KeysPanel open={true} onClose={vi.fn()} />);
    await flush();

    await act(async () => {
      byLabel<HTMLButtonElement>(container, /revoke echo/i).click();
      await Promise.resolve();
    });
    await flush();

    expect(gatewayMocks.blessClear).toHaveBeenCalledWith("Echo");
    expect(gatewayMocks.blessList).toHaveBeenCalledTimes(2);
    expect(container.textContent).not.toContain("Echo");
  });

  it("masks the value input by default", async () => {
    gatewayMocks.secretList.mockResolvedValueOnce([]);
    const { container } = render(<KeysPanel open={true} onClose={vi.fn()} />);
    await flush();

    expect(inputByName(container, "secret-value").type).toBe("password");
  });
});
