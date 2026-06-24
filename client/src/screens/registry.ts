import { registerDomain } from "../card/registry";
import type { DomainId } from "../domains";
import { CalendarDetail } from "./CalendarDetail";
import { FinanceDetail } from "./FinanceDetail";
import { GenericDomainDetail } from "./GenericDomainDetail";
import { GmailDetail } from "./GmailDetail";
import { ProjectsDetail } from "./ProjectsDetail";
import { ReviewDetail } from "./ReviewDetail";
import { StatusDetail } from "./StatusDetail";
import { TasksDetail } from "./TasksDetail";

/** Registers CLIENT-screens detail components into the CLIENT-card registry at module load. */
export const registeredDomainIds: DomainId[] = [
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
];

registerDomain("review", { detail: ReviewDetail });
registerDomain("schedule", { detail: CalendarDetail });
registerDomain("tasks", { detail: TasksDetail });
registerDomain("projects", { detail: ProjectsDetail });
registerDomain("email", { detail: GmailDetail });
registerDomain("finance", { detail: FinanceDetail });
registerDomain("people", { detail: GenericDomainDetail });
registerDomain("travel", { detail: GenericDomainDetail });
registerDomain("memory", { detail: GenericDomainDetail });
registerDomain("knowledge", { detail: GenericDomainDetail });
registerDomain("health", { detail: GenericDomainDetail });

export const statusDetail = StatusDetail;
