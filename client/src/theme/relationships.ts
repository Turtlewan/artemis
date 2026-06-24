import type { DomainId } from "../domains";

/** Every domain renders a spoke to the central brain core. */
export const SPOKE_DOMAINS = [
  "email",
  "people",
  "schedule",
  "tasks",
  "projects",
  "travel",
  "memory",
  "knowledge",
  "review",
  "health",
  "finance",
] as const satisfies readonly DomainId[];

/** Real domain relationship edges used by the neural-web skeleton. */
export const DOMAIN_RELATIONSHIPS = [
  ["email", "schedule"],
  ["email", "tasks"],
  ["email", "finance"],
  ["email", "people"],
  ["schedule", "tasks"],
  ["schedule", "travel"],
  ["schedule", "people"],
  ["finance", "tasks"],
  ["finance", "travel"],
  ["people", "travel"],
  ["memory", "people"],
  ["review", "finance"],
  ["review", "schedule"],
  ["projects", "tasks"],
  ["projects", "schedule"],
] as const satisfies readonly (readonly [DomainId, DomainId])[];
