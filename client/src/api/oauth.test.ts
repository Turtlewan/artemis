import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  invoke: vi.fn(),
}));

vi.mock("@tauri-apps/api/core", () => ({
  invoke: mocks.invoke,
}));

import * as oauth from "./oauth";

describe("oauth facade", () => {
  beforeEach(() => {
    mocks.invoke.mockReset();
  });

  it("invokes app_oauth_connect with scopes", async () => {
    const response = { consent_url: "https://accounts.google.com/o/oauth2/v2/auth" };
    mocks.invoke.mockResolvedValueOnce(response);

    await expect(oauth.oauthConnect(["scope-a"])).resolves.toEqual(response);
    expect(mocks.invoke).toHaveBeenCalledWith("app_oauth_connect", { scopes: ["scope-a"] });
  });

  it("returns client_not_configured connect responses", async () => {
    const response = { status: "client_not_configured" };
    mocks.invoke.mockResolvedValueOnce(response);

    await expect(oauth.oauthConnect(["scope-a"])).resolves.toEqual(response);
  });

  it("invokes app_oauth_status without args", async () => {
    const response = { account: "default", connected: true, granted_scopes: ["scope-a"] };
    mocks.invoke.mockResolvedValueOnce(response);

    await expect(oauth.oauthStatus()).resolves.toEqual(response);
    expect(mocks.invoke).toHaveBeenCalledWith("app_oauth_status", undefined);
  });

  it("invokes app_oauth_disconnect with an optional account", async () => {
    const response = { disconnected: true };
    mocks.invoke.mockResolvedValueOnce(response);

    await expect(oauth.oauthDisconnect("default")).resolves.toEqual(response);
    expect(mocks.invoke).toHaveBeenCalledWith("app_oauth_disconnect", { account: "default" });
  });
});
