import { invoke } from "@tauri-apps/api/core";
import { useState } from "react";

import {
  acceptSuggestion as acceptSuggestionCommand,
  rejectSuggestion as rejectSuggestionCommand,
} from "../api/gateway";
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
            <button className="screen-btn" type="button" aria-label={`Time-block: ${task.title}`} onClick={() => onAction("time-block", task)} disabled>
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
  const [suggestionDueAt, setSuggestionDueAt] = useState<Record<string, string>>({});

  const onTaskAction = (kind: string, task: TaskItem): void => {
    if (kind === "time-block") {
      setMessage("Time-blocking is unavailable.");
      return;
    }
    const command = `tasks.${kind}`;
    void action(command, { task_id: task.task_id }).then(() => setMessage(`${kind} applied.`));
  };

  const acceptSuggestion = (suggestionId: string): void => {
    const dueAt = suggestionDueAt[suggestionId]?.trim() || undefined;
    void acceptSuggestionCommand(suggestionId, dueAt).then(() => setMessage("Suggestion accepted."));
  };

  const rejectSuggestion = (suggestionId: string): void => {
    void rejectSuggestionCommand(suggestionId).then(() => setMessage("Suggestion rejected."));
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
                  <input
                    className="screen-input"
                    type="date"
                    aria-label={`Due date for ${suggestion.title}`}
                    value={suggestionDueAt[suggestion.suggestion_id] ?? ""}
                    onChange={(event) =>
                      setSuggestionDueAt((current) => ({
                        ...current,
                        [suggestion.suggestion_id]: event.target.value,
                      }))
                    }
                  />
                  <button className="screen-btn" type="button" onClick={() => acceptSuggestion(suggestion.suggestion_id)}>
                    Accept
                  </button>
                  <button className="screen-btn" type="button" onClick={() => rejectSuggestion(suggestion.suggestion_id)}>
                    Reject
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
