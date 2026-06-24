import type { DomainId } from "../domains";

/** Screen-local route metadata only; domain identity remains owned by domains.ts. */
export const ROUTE: Record<DomainId, string> = {
  email: "app_gmail_read",
  people: "app_people_read",
  schedule: "app_calendar_read",
  tasks: "app_tasks_read",
  projects: "app_projects_read",
  travel: "app_travel_read",
  memory: "app_memory_read",
  knowledge: "app_knowledge_read",
  review: "app_review_pending",
  health: "app_health_read",
  finance: "app_finance_read",
};

/** Owner-private screens require the unlocked vault tier. */
export const LOCK_TIER: Record<DomainId, "unlocked"> = {
  email: "unlocked",
  people: "unlocked",
  schedule: "unlocked",
  tasks: "unlocked",
  projects: "unlocked",
  travel: "unlocked",
  memory: "unlocked",
  knowledge: "unlocked",
  review: "unlocked",
  health: "unlocked",
  finance: "unlocked",
};
