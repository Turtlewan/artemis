export type DomainId =
  | "email"
  | "people"
  | "schedule"
  | "tasks"
  | "projects"
  | "travel"
  | "memory"
  | "knowledge"
  | "review"
  | "health"
  | "finance";

export type DomainCluster = "Comms" | "Planning" | "Knowledge" | "Self";

const labels: Record<DomainId, string> = {
  email: "Email",
  people: "People",
  schedule: "Schedule",
  tasks: "Tasks",
  projects: "Projects",
  travel: "Travel",
  memory: "Memory",
  knowledge: "Knowledge",
  review: "Review",
  health: "Health",
  finance: "Finance",
};

const clusters: Record<DomainId, DomainCluster> = {
  email: "Comms",
  people: "Comms",
  schedule: "Planning",
  tasks: "Planning",
  projects: "Planning",
  travel: "Planning",
  memory: "Knowledge",
  knowledge: "Knowledge",
  review: "Knowledge",
  health: "Self",
  finance: "Self",
};

export const domainLabel = (id: DomainId): string => (labels as Record<string, string>)[id] ?? id;

export const domainCluster = (id: DomainId): DomainCluster => clusters[id];
