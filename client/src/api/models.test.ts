import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  invoke: vi.fn(),
}));

vi.mock("@tauri-apps/api/core", () => ({
  invoke: mocks.invoke,
}));

import * as models from "./models";

describe("models facade", () => {
  beforeEach(() => {
    mocks.invoke.mockReset();
  });

  it("invokes app_models_get without args", async () => {
    const response: models.ModelsResponse = {
      roles: [
        {
          role: "reader",
          provider: "claude_code",
          model: "sonnet",
          constraints: { no_tools: true, temperature: null },
          eligible_providers: ["claude_code", "ollama"],
          editable_fields: ["provider", "model"],
        },
      ],
      providers: ["claude_code", "codex", "ollama", "router"],
      dropped_overrides: [{ role: "reader", reason: "no_tools_ineligible" }],
    };
    mocks.invoke.mockResolvedValueOnce(response);

    await expect(models.modelsGet()).resolves.toEqual(response);
    expect(mocks.invoke).toHaveBeenCalledWith("app_models_get", undefined);
  });

  it("invokes app_models_put and returns updated bindings", async () => {
    const response: models.ModelRole = {
      role: "loop_driver",
      provider: "codex",
      model: "gpt-5.5",
      constraints: { no_tools: false, temperature: null },
      eligible_providers: ["codex"],
      editable_fields: ["provider", "model"],
    };
    mocks.invoke.mockResolvedValueOnce(response);

    const result = await models.modelsPut("loop_driver", "codex", "gpt-5.5");

    expect(result).toEqual(response);
    expect(models.isRoleInvalid(result)).toBe(false);
    expect(mocks.invoke).toHaveBeenCalledWith("app_models_put", {
      role: "loop_driver",
      provider: "codex",
      model: "gpt-5.5",
    });
  });

  it("narrows app_models_put invalid responses", async () => {
    const response: models.RoleInvalid = {
      detail: "reader must resolve to a no-tools-capable provider",
    };
    mocks.invoke.mockResolvedValueOnce(response);

    const result = await models.modelsPut("reader", "codex", "gpt-5.5");

    expect(models.isRoleInvalid(result)).toBe(true);
    if (models.isRoleInvalid(result)) {
      expect(result.detail).toBe("reader must resolve to a no-tools-capable provider");
    }
  });

  it("invokes app_models_usage without args", async () => {
    const response: models.ModelUsageResponse = {
      roles: [
        {
          role: "selector",
          calls: 1,
          prompt_tokens: 2,
          completion_tokens: 4,
          avg_latency_ms: 7.0,
        },
      ],
    };
    mocks.invoke.mockResolvedValueOnce(response);

    await expect(models.modelsUsage()).resolves.toEqual(response);
    expect(mocks.invoke).toHaveBeenCalledWith("app_models_usage", undefined);
  });
});
