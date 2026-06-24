import { type FormEvent, type KeyboardEvent, useEffect, useId, useRef, useState } from "react";

import type { AskEngine } from "./EngineTag";
import { useAskStore, askStore } from "./askStore";
import { ResultRow } from "./ResultRow";

interface AskPopupProps {
  isOpen: boolean;
  onClose: () => void;
}

const focusableSelector = [
  "button:not([disabled])",
  "input:not([disabled])",
  "[href]",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

interface AskDisplayRow {
  id: string;
  text: string;
  engine: AskEngine;
  failedLocked?: boolean;
}

const styles = `
.ask-backdrop {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: grid;
  place-items: start center;
  padding: clamp(32px, 9vh, 92px) 18px 24px;
  background: color-mix(in srgb, var(--bg) 48%, transparent);
  opacity: 0;
  pointer-events: none;
  transition: opacity 180ms ease;
}

.ask-backdrop[data-open="true"] {
  opacity: 1;
  pointer-events: auto;
}

.ask-panel {
  width: min(720px, 100%);
  max-height: min(680px, calc(100vh - 56px));
  display: grid;
  grid-template-rows: auto auto minmax(120px, 1fr) auto;
  gap: 14px;
  padding: 18px;
  transform: translateY(-10px) scale(0.98);
  opacity: 0;
  transition:
    transform 180ms ease,
    opacity 180ms ease;
}

.ask-backdrop[data-open="true"] .ask-panel {
  transform: translateY(0) scale(1);
  opacity: 1;
}

.ask-header,
.ask-input-line,
.ask-footer,
.ask-result-row {
  display: flex;
  align-items: center;
}

.ask-header {
  gap: 12px;
}

.ask-brand-mark {
  width: 40px;
  height: 40px;
  display: grid;
  place-items: center;
  border-radius: 999px;
  border: 1px solid color-mix(in srgb, var(--p) 52%, transparent);
  box-shadow:
    inset 0 0 0 7px color-mix(in srgb, var(--p) 10%, transparent),
    0 0 22px color-mix(in srgb, var(--p) 28%, transparent);
}

.ask-brand-mark::after {
  content: "";
  width: 12px;
  height: 12px;
  border-radius: 999px;
  background: var(--a);
  box-shadow: 0 0 18px var(--a);
}

.ask-title {
  margin: 0;
  font-family: "Space Grotesk", system-ui, sans-serif;
  font-size: 1.2rem;
  line-height: 1.1;
}

.ask-close {
  margin-inline-start: auto;
}

.ask-input-line {
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid var(--hair);
  border-radius: 14px;
  background: color-mix(in srgb, var(--bg) 36%, transparent);
}

.ask-input-line label {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
}

.ask-input {
  min-width: 0;
  flex: 1;
  border: 0;
  background: transparent;
  color: var(--text);
  font: 600 1rem/1.2 "Space Grotesk", system-ui, sans-serif;
  caret-color: var(--p);
  outline: none;
}

.ask-mode-chip,
.ask-status-chip,
.ask-engine-tag {
  flex: 0 0 auto;
  border: 1px solid var(--hair);
  border-radius: 999px;
  padding: 4px 9px;
  color: var(--text);
  background: color-mix(in srgb, var(--p) 10%, transparent);
  font-size: 0.76rem;
  letter-spacing: 0;
  text-transform: uppercase;
}

.ask-results {
  min-height: 0;
  margin: 0;
  padding: 0 2px 2px;
  display: grid;
  align-content: start;
  gap: 10px;
  overflow: auto;
  scroll-padding-bottom: 16px;
  list-style: none;
}

.ask-result-row {
  gap: 12px;
  min-height: 68px;
  padding: 10px;
  border: 1px solid var(--hair);
  border-radius: 12px;
  background: color-mix(in srgb, var(--bg) 34%, transparent);
}

.ask-result-row__icon {
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border-radius: 12px;
  background: color-mix(in srgb, var(--p) 16%, transparent);
}

.ask-result-row__icon span {
  width: 13px;
  height: 13px;
  border-radius: 999px;
  background: var(--p);
  opacity: 0.86;
}

.ask-result-row__copy {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.ask-result-row__title,
.ask-result-row__subtitle {
  overflow-wrap: anywhere;
}

.ask-result-row__title {
  font-weight: 700;
}

.ask-result-row__subtitle {
  color: var(--muted);
  font-size: 0.9rem;
}

.ask-result-row .ask-engine-tag {
  margin-inline-start: auto;
}

.ask-engine-tag--review {
  border-color: var(--a);
  color: var(--a);
}

.ask-footer {
  flex-wrap: wrap;
  gap: 8px;
}

.ask-status-chip span {
  color: var(--p);
}

.ask-sr {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
}

@media (prefers-reduced-motion: reduce) {
  .ask-backdrop,
  .ask-panel {
    transition: none;
  }

  .ask-input {
    caret-color: auto;
  }
}
`;

/** Floating Ask Artemis dialog with manual focus trap and streaming status regions. */
export function AskPopup({ isOpen, onClose }: AskPopupProps) {
  const titleId = useId();
  const inputId = useId();
  const panelRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [text, setText] = useState("");
  const snapshot = useAskStore((current) => current);

  useEffect(() => {
    if (!isOpen) return;
    window.requestAnimationFrame(() => inputRef.current?.focus());
  }, [isOpen]);

  const focusable = (): HTMLElement[] => {
    if (panelRef.current === null) return [];
    const candidates = Array.from(panelRef.current.querySelectorAll<HTMLElement>(focusableSelector));
    if (inputRef.current === null) return candidates;
    return [inputRef.current, ...candidates.filter((candidate) => candidate !== inputRef.current)];
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
      return;
    }

    if (event.key !== "Tab") return;
    const candidates = focusable();
    const first = candidates[0];
    const last = candidates[candidates.length - 1];
    if (first === undefined || last === undefined) return;

    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
      return;
    }

    if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const onSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    const pending = text;
    setText("");
    void askStore.send(pending);
  };

  const assistantRows = snapshot.messages.filter((message) => message.role === "assistant");
  const rows: AskDisplayRow[] =
    assistantRows.length === 0 && snapshot.streaming === ""
      ? [{ id: "empty", text: "Ready when the vault is unlocked.", engine: "local" as const }]
      : assistantRows.map((message) => ({
          id: message.id,
          text: message.text === "" ? snapshot.streaming : message.text,
          engine: message.engine ?? "local",
          failedLocked: message.failedLocked,
        }));

  return (
    <>
      <style>{styles}</style>
      <div
        className="ask-backdrop"
        data-open={isOpen ? "true" : "false"}
        onMouseDown={(event) => {
          if (event.target === event.currentTarget) onClose();
        }}
      >
        {isOpen ? (
          <div
            ref={panelRef}
            className="ask-panel glass"
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            onKeyDown={onKeyDown}
          >
            <span className="glass-sheen" aria-hidden="true" />
            <header className="ask-header">
              <span className="ask-brand-mark" aria-hidden="true" />
              <h2 id={titleId} className="ask-title">
                Ask Artemis
              </h2>
              <button className="ask-close" type="button" aria-label="Close Ask Artemis" onClick={onClose}>
                x
              </button>
            </header>

            <form className="ask-input-line" onSubmit={onSubmit}>
              <label htmlFor={inputId}>Ask Artemis</label>
              <input
                ref={inputRef}
                id={inputId}
                className="ask-input caret-primary"
                value={text}
                onChange={(event) => setText(event.currentTarget.value)}
                aria-label="Ask Artemis"
                autoComplete="off"
              />
              <span className="ask-mode-chip">{snapshot.modeHint}</span>
            </form>

            <ol className="ask-results" aria-label="Ask results">
              {rows.map((row) => (
                <ResultRow
                  key={row.id}
                  title={row.failedLocked ? "Vault locked" : "Answer"}
                  subtitle={row.text}
                  engine={row.engine}
                  failedLocked={row.failedLocked}
                />
              ))}
            </ol>

            <footer className="ask-footer" aria-label="Engine status">
              {Object.entries(snapshot.engineStatus).map(([engine, active]) => (
                <span className="ask-status-chip" key={engine}>
                  <span aria-hidden="true">o</span> {engine} {active ? "ready" : "idle"}
                </span>
              ))}
            </footer>
            <div className="ask-sr" aria-live="polite">
              {snapshot.politeAnnouncement}
            </div>
            <div className="ask-sr" role="alert" aria-live="assertive">
              {snapshot.assertiveAnnouncement}
            </div>
          </div>
        ) : null}
      </div>
    </>
  );
}
