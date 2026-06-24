import { invoke } from "@tauri-apps/api/core";
import { useState } from "react";

import type { DomainDetailProps } from "../card/types";
import { DomainDetailShell, EngineTagText } from "./DomainDetailShell";
import type { TasksRead } from "./dtos";
import { useDomainRead, type DomainReader } from "./useDomainRead";

interface TasksDetailProps extends DomainDetailProps {
  reader?: DomainReader<TasksRead>;
  action?: (name: string, payload: Record<string, unknown>) => Promise<unknown>;
}

type TaskItem = { title: string; due?: string; task_id: string };

const TaskList = ({
  title,
  items,
  onAction,
}: {
  title: string;
  items: TaskItem[];
  onAction: (action: string, task: TaskItem) => void;
}) => (
  <section>
    <h3 className="screen-eyebrow">
      {title} <span className="screen-muted">{items.length}</span>
    </h3>
    <ul className="screen-list" role="list">
      {items.map((task) => (
        <li className="screen-row" key={task.task_id}>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <button className="screen-btn" type="button" aria-label={`Check off: ${task.title}`} onClick={() => onAction("complete", task)}>
              ✓
            </button>
            <span style={{ flex: 1 }}>
              {task.title} {task.due !== undefined && <span className="screen-pill">{task.due}</span>}
            </span>
            <button className="screen-btn" type="button" aria-label={`Reschedule: ${task.title}`} onClick={() => onAction("reschedule", task)}>
              Reschedule
            </button>
            <button className="screen-btn" type="button" aria-label={`Time-block: ${task.title}`} onClick={() => onAction("time-block", task)}>
              Time-block
            </button>
          </div>
        </li>
      ))}
    </ul>
  </section>
);

export function TasksDetail({
  domainId,
  onClose,
  reader,
  action = (name, payload) => invoke(name, payload),
}: TasksDetailProps) {
  const { data, loading, error } = useDomainRead<TasksRead>(domainId, reader);
  const [message, setMessage] = useState("");

  const onTaskAction = (kind: string, task: TaskItem): void => {
    const command = kind === "time-block" ? "calendar.schedule_task" : `tasks.${kind}`;
    void action(command, { task_id: task.task_id }).then(() => setMessage(`${kind} applied.`));
  };

  const acceptSuggestion = (suggestionId: string): void => {
    void action("tasks.accept_suggestion", { suggestion_id: suggestionId }).then(() => setMessage("Suggestion accepted."));
  };

  return (
    <DomainDetailShell
      domainId={domainId}
      title="Tasks"
      engine={<EngineTagText value="local" />}
      loading={loading}
      error={error}
      empty={data !== null && data.today.length + data.overdue.length + data.upcoming.length === 0 ? "No tasks due." : null}
      onClose={onClose}
    >
      {data !== null && (
        <div className="screen-split">
          <div>
            <TaskList title="Due" items={data.today} onAction={onTaskAction} />
            <TaskList title="Overdue" items={data.overdue} onAction={onTaskAction} />
            <TaskList title="Upcoming" items={data.upcoming} onAction={onTaskAction} />
          </div>
          <aside>
            <h3 className="screen-eyebrow">Captured</h3>
            <ul className="screen-list" role="list" aria-label="Capture suggestions">
              {data.suggestions.map((suggestion) => (
                <li className="screen-row" key={suggestion.suggestion_id}>
                  <p>{suggestion.title}</p>
                  <button className="screen-btn" type="button" onClick={() => acceptSuggestion(suggestion.suggestion_id)}>
                    Accept
                  </button>
                </li>
              ))}
            </ul>
            <p className="screen-muted">Free-form task creation lives in Ask Artemis.</p>
            <p role="status" aria-live="polite" className="screen-status">
              {message}
            </p>
          </aside>
        </div>
      )}
    </DomainDetailShell>
  );
}
