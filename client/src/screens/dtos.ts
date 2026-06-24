export type EngineTag = "local" | "codex" | "review";

/** Calendar screen DTO: richer than the current live wire shape; live mapping is deferred. */
export interface CalendarRead {
  events: {
    id: string;
    title: string;
    start: string;
    end: string;
    kind: "event" | "held_tentative";
    attendees?: string[];
    rsvp?: "yes" | "no" | "maybe";
  }[];
  tasksDueByDay: Record<string, { title: string; task_id: string }[]>;
}

/** Tasks screen DTO for the locked Due / Overdue / Upcoming view. */
export interface TasksRead {
  overdue: { title: string; due: string; task_id: string }[];
  today: { title: string; due?: string; task_id: string }[];
  upcoming: { title: string; due?: string; task_id: string }[];
  suggestions: { title: string; suggestion_id: string }[];
}

/** Projects screen DTO for status-led project rows. */
export interface ProjectsRead {
  projects: {
    id: string;
    name: string;
    status: "active" | "blocked" | "done";
    target?: string;
    openTasks: number;
  }[];
}

/** Gmail screen DTO; backend read connector is fake/live gated for now. */
export interface GmailRead {
  needsYou: { id: string; sender: string; subject: string; why: string }[];
  signal: { id: string; sender: string; subject: string; ts: string }[];
}

/** Finance screen DTO for the compact awareness page; all edits are instant local state. */
export interface FinanceRead {
  week_total: number;
  mtd_total: number;
  daily: { weekday: string; date: string; amount: number | null; is_today: boolean }[];
  categories: { name: string; amount: number; pct: number; color: string }[];
  transactions: { date: string; merchant: string; category: string; amount: number }[];
  bills: {
    name: string;
    when: string;
    overdue: boolean;
    amount: number;
    is_sub: boolean;
    paid: boolean;
  }[];
  unusual: { merchant: string; amount: number; why: string } | null;
  duplicate: { why: string } | null;
  ambiguous: { merchant: string; amount: number; why: string } | null;
}

/** Generic tail DTO used until each domain gets a bespoke design and backend. */
export interface GenericRead {
  count: number;
  items: { title: string; subtitle?: string; engine?: EngineTag }[];
}

export type ScreenDTO =
  | CalendarRead
  | TasksRead
  | ProjectsRead
  | GmailRead
  | FinanceRead
  | GenericRead;
