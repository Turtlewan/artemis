// @vitest-environment jsdom
import { act } from "react";
import type { ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ReviewItem } from "../api/dto";
import { connectionStore } from "../state/connection";
import { ReviewDetail } from "./ReviewDetail";
import type { PendingAction } from "./dtos";

const recipe: ReviewItem = {
  name: "Morning recipe",
  description: "Runs the digest",
  status: "pending",
  action_class: "external",
  safety: "needs_review",
  explanation: "Owner must approve this exact recipe.",
};

const action: PendingAction = {
  id: "act-1",
  module: "calendar",
  tool: "create_event",
  summary: "Create lunch with Sam",
  action_class: "takes-action",
  status: "pending",
  created_at: "2026-06-27T00:00:00Z",
  expires_at: "2999-06-27T01:00:00Z",
  result: null,
};

const roleSelector = (role: string): string => `[role="${role}"]`;

const getByRole = (container: HTMLElement, role: string, name?: RegExp): HTMLElement => {
  const candidates = Array.from(container.querySelectorAll<HTMLElement>(roleSelector(role)));
  if (role === "button") {
    candidates.push(...Array.from(container.querySelectorAll<HTMLButtonElement>("button")));
  }

  const match = candidates.find((candidate) => {
    if (name === undefined) return true;
    const label = candidate.getAttribute("aria-label");
    return name.test(`${label ?? ""} ${candidate.textContent ?? ""}`);
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

const renderReview = async ({
  actions = [action],
  approveAction = vi.fn().mockResolvedValue({ ok: true }),
  rejectAction = vi.fn().mockResolvedValue({ ok: true }),
}: {
  actions?: PendingAction[];
  approveAction?: (id: string) => Promise<unknown>;
  rejectAction?: (id: string) => Promise<unknown>;
} = {}): Promise<{ container: HTMLDivElement; approveAction: (id: string) => Promise<unknown>; rejectAction: (id: string) => Promise<unknown> }> => {
  const view = render(
    <ReviewDetail
      domainId="review"
      onClose={vi.fn()}
      actionsReader={() => Promise.resolve(actions)}
      actionApprove={approveAction}
      actionReject={rejectAction}
      reader={() => Promise.resolve([recipe])}
      autoReader={() => Promise.resolve(false)}
      approve={() => Promise.resolve({ ok: true })}
      reject={() => Promise.resolve({ ok: true })}
    />,
  );
  await act(async () => {
    await Promise.resolve();
  });
  return { container: view.container, approveAction, rejectAction };
};

describe("ReviewDetail pending actions", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    connectionStore.resetForTest();
    window.requestAnimationFrame = (callback: FrameRequestCallback): number => {
      callback(0);
      return 0;
    };
  });

  it("renders pending actions without args and keeps the recipe review section", async () => {
    const actionWithArgs = { ...action, args: { hidden: true } } as PendingAction;
    const { container } = await renderReview({ actions: [actionWithArgs] });

    expect(container.textContent).toContain("Pending actions");
    expect(container.textContent).toContain("Create lunch with Sam");
    expect(container.textContent).toContain("calendar.create_event");
    expect(container.textContent).toContain("2999-06-27T01:00:00Z");
    expect(container.textContent).not.toContain("hidden");
    expect(container.textContent).toContain("Recipe review");
    expect(container.textContent).toContain("Morning recipe");
  });

  it("optimistically removes an approved action and keeps it removed on success", async () => {
    const approveAction = vi.fn().mockResolvedValue({ ok: true });
    const { container } = await renderReview({ approveAction });

    await act(async () => {
      getByRole(container, "button", /approve: create lunch with sam/i).click();
    });

    expect(approveAction).toHaveBeenCalledWith("act-1");
    expect(container.textContent).not.toContain("Create lunch with Sam");
    expect(container.textContent).toContain("Action approved.");
  });

  it("restores an approved action and shows a recoverable message on 409", async () => {
    const approveAction = vi.fn().mockRejectedValue({ kind: "http", status: 409 });
    const { container } = await renderReview({ approveAction });

    await act(async () => {
      getByRole(container, "button", /approve: create lunch with sam/i).click();
    });

    expect(container.textContent).toContain("Create lunch with Sam");
    expect(container.textContent).toContain("Pending action changed before review.");
  });

  it("restores a rejected action and shows a recoverable message on 404", async () => {
    const rejectAction = vi.fn().mockRejectedValue({ kind: "http", status: 404 });
    const { container } = await renderReview({ rejectAction });

    await act(async () => {
      getByRole(container, "button", /reject: create lunch with sam/i).click();
    });

    expect(container.textContent).toContain("Create lunch with Sam");
    expect(container.textContent).toContain("Pending action changed before review.");
  });

  it("restores on vault lock and routes through the re-lock path", async () => {
    connectionStore.onPaired();
    connectionStore.onConnected();
    connectionStore.onUnlocked();
    const approveAction = vi.fn().mockRejectedValue({ kind: "vaultLocked" });
    const { container } = await renderReview({ approveAction });

    await act(async () => {
      getByRole(container, "button", /approve: create lunch with sam/i).click();
    });

    expect(connectionStore.getSnapshot().state).toBe("connectedLocked");
    expect(container.textContent).toContain("Unlock required");

    await act(async () => {
      connectionStore.onUnlocked();
    });
    expect(container.textContent).toContain("Create lunch with Sam");
  });

  it("reject also routes vault lock through the re-lock path", async () => {
    connectionStore.onPaired();
    connectionStore.onConnected();
    connectionStore.onUnlocked();
    const rejectAction = vi.fn().mockRejectedValue({ kind: "vaultLocked" });
    const { container } = await renderReview({ rejectAction });

    await act(async () => {
      getByRole(container, "button", /reject: create lunch with sam/i).click();
    });

    expect(connectionStore.getSnapshot().state).toBe("connectedLocked");
    expect(container.textContent).toContain("Unlock required");
  });

  it("shows the pending actions empty state", async () => {
    const { container } = await renderReview({ actions: [] });

    expect(container.textContent).toContain("No pending actions.");
    expect(container.textContent).toContain("Morning recipe");
  });
});
