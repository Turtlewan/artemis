// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { connectionStore } from "../state/connection";
import { TasksDetail } from "./TasksDetail";
import type { TasksRead } from "./dtos";

const apiMocks = vi.hoisted(() => ({
  acceptSuggestion: vi.fn(),
  rejectSuggestion: vi.fn(),
}));

vi.mock("../api/gateway", () => ({
  acceptSuggestion: apiMocks.acceptSuggestion,
  rejectSuggestion: apiMocks.rejectSuggestion,
}));

const tasksRead: TasksRead = {
  overdue: [],
  today: [{ title: "Reply to landlord", task_id: "task-1" }],
  upcoming: [],
  suggestions: [{ title: "Book Penang flights", suggestion_id: "sug-1" }],
};

const renderTasks = async (
  action = vi.fn().mockResolvedValue({ ok: true }),
): Promise<{ container: HTMLDivElement; root: Root; action: ReturnType<typeof vi.fn> }> => {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <TasksDetail
        domainId="tasks"
        onClose={vi.fn()}
        reader={() => Promise.resolve(tasksRead)}
        action={action}
      />,
    );
    await Promise.resolve();
  });
  return { container, root, action };
};

describe("TasksDetail task suggestions", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    connectionStore.resetForTest();
    connectionStore.onPaired();
    connectionStore.onConnected();
    connectionStore.onUnlocked();
    apiMocks.acceptSuggestion.mockReset().mockResolvedValue({ task: { id: "task-2" } });
    apiMocks.rejectSuggestion.mockReset().mockResolvedValue({ ok: true });
  });

  it("accepts suggestions with a due date and rejects through owner commands", async () => {
    const { container } = await renderTasks();
    const dueInput = container.querySelector<HTMLInputElement>(
      'input[aria-label="Due date for Book Penang flights"]',
    );
    if (dueInput === null) throw new Error("missing due date input");

    await act(async () => {
      // Use the native value setter so React's value-tracker registers the
      // change and fires onChange (a direct `.value =` assignment is ignored).
      const setValue = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )?.set;
      setValue?.call(dueInput, "2026-07-02");
      dueInput.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => {
      getButton(container, "Accept").click();
    });
    await act(async () => {
      getButton(container, "Reject").click();
    });

    expect(apiMocks.acceptSuggestion).toHaveBeenCalledWith("sug-1", "2026-07-02");
    expect(apiMocks.rejectSuggestion).toHaveBeenCalledWith("sug-1");
  });

  it("keeps external time-block scheduling disabled and uninvoked", async () => {
    const action = vi.fn().mockResolvedValue({ ok: true });
    const { container } = await renderTasks(action);
    const timeBlock = getButton(container, "Time-block") as HTMLButtonElement;

    expect(timeBlock.disabled).toBe(true);

    await act(async () => {
      timeBlock.click();
    });

    expect(action).not.toHaveBeenCalledWith("calendar.schedule_task", expect.anything());
  });
});

const getButton = (container: HTMLElement, label: string): HTMLButtonElement => {
  const button = Array.from(container.querySelectorAll("button")).find(
    (candidate) => candidate.textContent === label,
  );
  if (button === undefined) throw new Error(`missing button ${label}`);
  return button;
};
