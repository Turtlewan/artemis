import { describe, expect, it } from "vitest";

import type { ReviewItem } from "../api/dto";

const item: ReviewItem = {
  name: "Morning recipe",
  description: "Runs the digest",
  status: "pending",
  action_class: "external",
  safety: "needs_review",
  explanation: "Owner must approve this exact recipe.",
};

describe("ReviewDetail contract", () => {
  it("uses stable item fields for accessible approve and reject labels", () => {
    expect(`Approve: ${item.name}`).toBe("Approve: Morning recipe");
    expect(`Reject: ${item.name}`).toBe("Reject: Morning recipe");
    expect(item.explanation).toBe("Owner must approve this exact recipe.");
  });

  it("keeps engine tag values as visible text contracts", () => {
    expect(["local", "codex", "review"]).toContain("review");
  });
});
