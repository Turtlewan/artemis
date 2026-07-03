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
  oauthConnect: vi.fn(),
  oauthStatus: vi.fn(),
  oauthDisconnect: vi.fn(),
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

vi.mock("../api/oauth", () => ({
  oauthConnect: gatewayMocks.oauthConnect,
  oauthStatus: gatewayMocks.oauthStatus,
  oauthDisconnect: gatewayMocks.oauthDisconnect,
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
    gatewayMocks.oauthConnect.mockReset();
    gatewayMocks.oauthStatus.mockReset();
    gatewayMocks.oauthDisconnect.mockReset();
    vi.unstubAllGlobals();
    gatewayMocks.blessList.mockResolvedValue([]);
    gatewayMocks.oauthStatus.mockResolvedValue({
      account: "default",
      connected: false,
      granted_scopes: [],
      connect_pending: false,
      last_connect_error: null,
    });
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

  it("connects Google through the command without opening a URL", async () => {
    const open = vi.fn();
    vi.stubGlobal("open", open);
    gatewayMocks.secretList.mockResolvedValue([]);
    gatewayMocks.oauthConnect.mockResolvedValueOnce({
      consent_url: "https://accounts.google.com/o/oauth2/v2/auth",
    });
    const { container } = render(<KeysPanel open={true} onClose={vi.fn()} />);
    await flush();

    await act(async () => {
      buttonByText(container, /^connect$/i).click();
      await Promise.resolve();
    });
    await flush();

    expect(gatewayMocks.oauthConnect).toHaveBeenCalledWith([
      "https://www.googleapis.com/auth/calendar.readonly",
    ]);
    expect(open).not.toHaveBeenCalled();
    expect(container.textContent).toContain("A browser window opened");
    expect(container.textContent).toContain("https://accounts.google.com/o/oauth2/v2/auth");
  });

  it("shows the Google client configuration prompt", async () => {
    gatewayMocks.secretList.mockResolvedValue([]);
    gatewayMocks.oauthConnect.mockResolvedValueOnce({ status: "client_not_configured" });
    const { container } = render(<KeysPanel open={true} onClose={vi.fn()} />);
    await flush();

    await act(async () => {
      buttonByText(container, /^connect$/i).click();
      await Promise.resolve();
    });
    await flush();

    expect(container.textContent).toContain("Add your Google client ID/secret above first.");
  });

  it("renders the connected Google account and granted scopes", async () => {
    gatewayMocks.secretList.mockResolvedValue([]);
    gatewayMocks.oauthStatus.mockResolvedValueOnce({
      account: "default",
      connected: true,
      granted_scopes: ["scope-a", "scope-b"],
      connect_pending: false,
      last_connect_error: null,
    });
    const { container } = render(<KeysPanel open={true} onClose={vi.fn()} />);
    await flush();

    expect(container.textContent).toContain("Connected: default");
    expect(container.textContent).toContain("scope-a");
    expect(container.textContent).toContain("scope-b");
  });

  it("shows a pending connect while the consent flow is open", async () => {
    gatewayMocks.secretList.mockResolvedValue([]);
    gatewayMocks.oauthStatus.mockResolvedValueOnce({
      account: "default",
      connected: false,
      granted_scopes: [],
      connect_pending: true,
      last_connect_error: null,
    });
    const { container } = render(<KeysPanel open={true} onClose={vi.fn()} />);
    await flush();

    expect(container.textContent).toContain("Waiting for Google consent");
    expect(container.textContent).not.toContain("No Google account connected.");
  });

  it("surfaces a failed Google connect distinctly", async () => {
    gatewayMocks.secretList.mockResolvedValue([]);
    gatewayMocks.oauthStatus.mockResolvedValueOnce({
      account: "default",
      connected: false,
      granted_scopes: [],
      connect_pending: false,
      last_connect_error: "Google OAuth token exchange failed",
    });
    const { container } = render(<KeysPanel open={true} onClose={vi.fn()} />);
    await flush();

    expect(container.textContent).toContain(
      "Google connect failed: Google OAuth token exchange failed",
    );
    expect(container.textContent).not.toContain("No Google account connected.");
  });

  it("disconnects Google and refreshes the status list", async () => {
    gatewayMocks.secretList.mockResolvedValue([]);
    gatewayMocks.oauthStatus
      .mockResolvedValueOnce({
        account: "default",
        connected: true,
        granted_scopes: ["scope-a"],
        connect_pending: false,
        last_connect_error: null,
      })
      .mockResolvedValueOnce({
        account: "default",
        connected: false,
        granted_scopes: [],
        connect_pending: false,
        last_connect_error: null,
      });
    gatewayMocks.oauthDisconnect.mockResolvedValueOnce({ disconnected: true });
    const { container } = render(<KeysPanel open={true} onClose={vi.fn()} />);
    await flush();

    await act(async () => {
      byLabel<HTMLButtonElement>(container, /disconnect default/i).click();
      await Promise.resolve();
    });
    await flush();

    expect(gatewayMocks.oauthDisconnect).toHaveBeenCalledWith("default");
    expect(gatewayMocks.oauthStatus).toHaveBeenCalledTimes(2);
    expect(container.textContent).toContain("No Google account connected.");
    expect(container.textContent).not.toContain("Connected: default");
  });

  it("surfaces a reconnect Google prompt", async () => {
    gatewayMocks.secretList.mockResolvedValueOnce([]);
    const { container } = render(
      <KeysPanel open={true} onClose={vi.fn()} reconnectGoogle={true} />,
    );
    await flush();

    expect(container.textContent).toContain(
      "Reconnect Google before running Google-backed capabilities.",
    );
  });

  it("masks the value input by default", async () => {
    gatewayMocks.secretList.mockResolvedValueOnce([]);
    const { container } = render(<KeysPanel open={true} onClose={vi.fn()} />);
    await flush();

    expect(inputByName(container, "secret-value").type).toBe("password");
  });
});
