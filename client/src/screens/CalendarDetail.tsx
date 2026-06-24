import { invoke } from "@tauri-apps/api/core";
import { useMemo, useState } from "react";

import type { DomainDetailProps } from "../card/types";
import { DomainDetailShell, EngineTagText } from "./DomainDetailShell";
import type { CalendarRead } from "./dtos";
import { useDomainRead, type DomainReader } from "./useDomainRead";

interface CalendarDetailProps extends DomainDetailProps {
  reader?: DomainReader<CalendarRead>;
  stage?: (name: string, payload: Record<string, unknown>) => Promise<unknown>;
}

const fmtDate = (value: string): string => value.slice(0, 10);
const fmtTime = (value: string): string => value.slice(11, 16);
const addDays = (date: Date, days: number): Date => {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
};
const isoDay = (date: Date): string => date.toISOString().slice(0, 10);

const fallbackDay = "2026-06-23";

export function CalendarDetail({
  domainId,
  onClose,
  reader,
  stage = (name, payload) => invoke("app_stage_pending_action", { name, payload }),
}: CalendarDetailProps) {
  const { data, loading, error } = useDomainRead<CalendarRead>(domainId, reader);
  const [view, setView] = useState<"month" | "week">("month");
  const [selectedDay, setSelectedDay] = useState(fallbackDay);
  const [staged, setStaged] = useState("");

  const days = useMemo(() => {
    const base = new Date(`${selectedDay}T00:00:00`);
    const start = addDays(base, -((base.getDay() + 6) % 7));
    return Array.from({ length: view === "month" ? 14 : 7 }, (_, index) => isoDay(addDays(start, index)));
  }, [selectedDay, view]);

  const events = data?.events ?? [];
  const dayEvents = events.filter((event) => fmtDate(event.start) === selectedDay);
  const dayTasks = data?.tasksDueByDay[selectedDay] ?? [];

  const stageExternal = async (title: string): Promise<void> => {
    await stage("calendar.external_effect", { title, selectedDay });
    setStaged("staged for your review ->");
  };

  return (
    <DomainDetailShell
      domainId={domainId}
      title="Calendar"
      engine={<EngineTagText value="review" />}
      loading={loading}
      error={error}
      empty={data !== null && events.length === 0 ? "No calendar items." : null}
      onClose={onClose}
    >
      <div className="screen-split">
        <div>
          <div role="group" aria-label="Calendar view" style={{ display: "flex", gap: 6 }}>
            <button className="screen-btn" type="button" aria-pressed={view === "month"} onClick={() => setView("month")}>
              Month
            </button>
            <button className="screen-btn" type="button" aria-pressed={view === "week"} onClick={() => setView("week")}>
              Week
            </button>
            <button className="screen-btn" type="button" onClick={() => setSelectedDay(fallbackDay)}>
              Today
            </button>
            <button className="screen-btn" type="button" onClick={() => setStaged("Morning find-time held locally.")}>
              morning find-time
            </button>
          </div>
          <ul className="screen-list" role="list" aria-label={`${view} days`} style={{ marginTop: 12 }}>
            {days.map((day) => (
              <li key={day}>
                <button className="screen-btn" type="button" onClick={() => setSelectedDay(day)}>
                  {day}
                </button>
              </li>
            ))}
          </ul>
        </div>
        <aside aria-label="Selected day panel">
          <h3>{selectedDay}</h3>
          <p className="screen-muted">
            {dayEvents.length} events - {dayTasks.length} tasks due
          </p>
          <h4 className="screen-eyebrow">Schedule</h4>
          <ul className="screen-list" role="list">
            {dayEvents.map((event) => (
              <li
                className="screen-row"
                key={event.id}
                data-kind={event.kind}
                style={event.kind === "held_tentative" ? { borderLeft: "2px dashed var(--a)", paddingLeft: 8 } : undefined}
              >
                <span className="screen-muted">{fmtTime(event.start)}</span> <strong>{event.title}</strong>{" "}
                {event.kind === "held_tentative" && <span className="screen-pill">held tentative</span>}
                <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
                  <button className="screen-btn" type="button">
                    View event
                  </button>
                  <button className="screen-btn" type="button" onClick={() => setStaged("Personal reminder added.")}>
                    Reminder
                  </button>
                  {event.attendees !== undefined && event.attendees.length > 0 && (
                    <button className="screen-btn" type="button" onClick={() => void stageExternal(event.title)}>
                      RSVP
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
          <h4 className="screen-eyebrow">Tasks due</h4>
          <ul className="screen-list" role="list">
            {dayTasks.map((task) => (
              <li className="screen-row" key={task.task_id}>
                {task.title}
              </li>
            ))}
          </ul>
          <button className="screen-btn" type="button" onClick={() => setStaged("Focus block added inline.")}>
            Add focus block
          </button>
          <p role="status" aria-live="polite" className="screen-status">
            {staged}
          </p>
        </aside>
      </div>
    </DomainDetailShell>
  );
}
