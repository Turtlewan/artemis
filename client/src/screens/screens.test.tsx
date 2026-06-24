import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { getDomainDetail } from "../card/registry";
import type { DomainId } from "../domains";
import { connectionStore } from "../state/connection";
import { DomainDetailShell, EngineTagText } from "./DomainDetailShell";
import { ROUTE } from "./domainRoutes";
import type { CalendarRead, FinanceRead, GenericRead, GmailRead, ProjectsRead, TasksRead } from "./dtos";
import { registeredDomainIds, statusDetail } from "./registry";

vi.mock("../state/connection", async () => {
  const actual = await vi.importActual<typeof import("../state/connection")>("../state/connection");
  return {
    ...actual,
    useConnection: () => actual.connectionStore.getSnapshot(),
  };
});

const allIds: DomainId[] = [
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

describe("screen routes and registry", () => {
  it("maps every canonical domain id to a read route", () => {
    expect(Object.keys(ROUTE).sort()).toEqual([...allIds].sort());
    expect(ROUTE.schedule).toBe("app_calendar_read");
    expect(ROUTE.email).toBe("app_gmail_read");
    expect(ROUTE.finance).toBe("app_finance_read");
  });

  it("registers all 11 domain detail components including projects", () => {
    expect(registeredDomainIds.sort()).toEqual([...allIds].sort());
    for (const id of allIds) expect(getDomainDetail(id)).toBeDefined();
    expect(getDomainDetail("projects")).toBeDefined();
    expect(statusDetail).toBeDefined();
  });
});

describe("DomainDetailShell", () => {
  it("renders a title, labelled internal scroll container, engine tag, and status states", () => {
    connectionStore.resetForTest();
    connectionStore.onPaired();
    connectionStore.onConnected();
    connectionStore.onUnlocked();

    const loading = renderToStaticMarkup(
      <DomainDetailShell domainId="tasks" title="Tasks" engine={<EngineTagText value="local" />} loading onClose={vi.fn()}>
        <p>Loaded</p>
      </DomainDetailShell>,
    );

    expect(loading).toContain("<h2");
    expect(loading).toContain("Tasks");
    expect(loading).toContain('tabindex="0"');
    expect(loading).toContain('aria-label="Tasks details"');
    expect(loading).toContain('role="status"');
    expect(loading).toContain("local");

    const empty = renderToStaticMarkup(
      <DomainDetailShell domainId="tasks" title="Tasks" empty="Nothing here." onClose={vi.fn()}>
        <p>Loaded</p>
      </DomainDetailShell>,
    );
    expect(empty).toContain("Nothing here.");
  });

  it("renders the connected-locked re-unlock prompt for unlocked-tier domains", () => {
    connectionStore.resetForTest();
    connectionStore.onPaired();
    connectionStore.onConnected();

    const markup = renderToStaticMarkup(
      <DomainDetailShell domainId="finance" title="Finance" onClose={vi.fn()}>
        <p>Loaded</p>
      </DomainDetailShell>,
    );

    expect(markup).toContain("Unlock required");
    expect(markup).toContain("Re-unlock");
  });
});

describe("locked screen DTO examples", () => {
  it("accepts the rich Calendar, Tasks, Projects, Gmail, Finance, and generic DTO shapes", () => {
    const calendar: CalendarRead = {
      events: [{ id: "e1", title: "Team sync invite", start: "2026-06-23T16:30", end: "2026-06-23T17:00", kind: "held_tentative", attendees: ["Debby"] }],
      tasksDueByDay: { "2026-06-23": [{ title: "Reply to landlord", task_id: "t1" }] },
    };
    const tasks: TasksRead = {
      overdue: [{ title: "Pay SP Group bill", due: "Yesterday", task_id: "t2" }],
      today: [{ title: "Reply to landlord", task_id: "t1" }],
      upcoming: [{ title: "Call dentist", due: "Fri", task_id: "t3" }],
      suggestions: [{ title: "Book Penang flights", suggestion_id: "s1" }],
    };
    const projects: ProjectsRead = { projects: [{ id: "p1", name: "Penang", status: "active", target: "2026-07-12", openTasks: 3 }] };
    const gmail: GmailRead = {
      needsYou: [{ id: "m1", sender: "Debby", subject: "Team sync", why: "Needs reply" }],
      signal: [{ id: "m2", sender: "Bank", subject: "Statement", ts: "09:00" }],
    };
    const finance: FinanceRead = {
      week_total: 742,
      mtd_total: 2418,
      daily: [{ weekday: "Tue", date: "23 Jun", amount: 84.2, is_today: true }, { weekday: "Wed", date: "24 Jun", amount: null, is_today: false }],
      categories: [{ name: "Groceries", amount: 220, pct: 30, color: "#58c6ff" }],
      transactions: [{ date: "23 Jun", merchant: "SP Group", category: "Bills", amount: -84.2 }],
      bills: [{ name: "SP Group", when: "Fri", overdue: false, amount: -84.2, is_sub: false, paid: false }],
      unusual: { merchant: "Camera shop", amount: -620, why: "Above normal" },
      duplicate: { why: "Two similar taxi charges" },
      ambiguous: { merchant: "PayNow", amount: 500, why: "Could be transfer or income" },
    };
    const generic: GenericRead = { count: 1, items: [{ title: "Alice", subtitle: "VIP", engine: "local" }] };

    expect(calendar.events[0]?.kind).toBe("held_tentative");
    expect(tasks.suggestions[0]?.suggestion_id).toBe("s1");
    expect(projects.projects[0]?.status).toBe("active");
    expect(gmail.needsYou[0]?.why).toBe("Needs reply");
    expect(finance.daily[1]?.amount).toBeNull();
    expect(generic.items[0]?.engine).toBe("local");
  });
});
