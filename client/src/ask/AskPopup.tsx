import { type FormEvent, type KeyboardEvent, useEffect, useId, useRef, useState } from "react";

import { useAskStore, askStore } from "./askStore";

interface AskPopupProps {
  isOpen: boolean;
  onClose: () => void;
  onVoiceTrigger?: (options: { speak: boolean }) => void | Promise<void>;
}

const focusableSelector = [
  "button:not([disabled])",
  "input:not([disabled])",
  "[href]",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

const styles = `
.ask-backdrop {
  /* Pin the Ask popup palette (matches the mockup) so it does NOT shift with the
     app's ambient season/time theme. Tweak these to retheme the popup. */
  --bg: #060c14;
  --p: #58c6ff;
  --a: #fff0d8;
  --text: #eef7ff;
  --muted: #a8bccb;
  --hair: color-mix(in srgb, #58c6ff 26%, transparent);

  position: fixed;
  inset: 0;
  z-index: 60;
  display: grid;
  place-items: start center;
  padding: clamp(32px, 9vh, 92px) 18px 24px;
  background: color-mix(in srgb, var(--bg) 55%, transparent);
  opacity: 0;
  pointer-events: none;
  transition: opacity 180ms ease;
}
.ask-backdrop[data-open="true"] {
  opacity: 1;
  pointer-events: auto;
}

.ask-panel {
  width: min(640px, 100%);
  display: flex;
  flex-direction: column;
  background: color-mix(in srgb, var(--bg) 82%, #0c1626 18%);
  border: 1px solid var(--hair);
  border-radius: 16px;
  box-shadow: 0 30px 80px rgba(0, 0, 0, 0.55);
  overflow: hidden;
  backdrop-filter: blur(18px);
  color: var(--text);
  transform: translateY(-10px) scale(0.98);
  opacity: 0;
  transition: transform 180ms ease, opacity 180ms ease;
}
.ask-backdrop[data-open="true"] .ask-panel {
  transform: none;
  opacity: 1;
}

.ask-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 18px;
  border-bottom: 1px solid var(--hair);
}
.ask-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--a);
  box-shadow: 0 0 14px var(--a);
}
.ask-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.01em;
}
.ask-engine {
  margin-left: auto;
  font-size: 11px;
  color: var(--p);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  border: 1px solid var(--hair);
  border-radius: 999px;
  padding: 4px 9px;
}
.ask-chip {
  font-size: 11px;
  color: var(--a);
  border: 1px solid var(--hair);
  border-radius: 999px;
  padding: 4px 9px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.ask-close {
  background: transparent;
  border: 0;
  color: var(--muted);
  font-size: 20px;
  line-height: 1;
  cursor: pointer;
  padding: 4px;
}
.ask-close:hover {
  color: var(--text);
}

/* Fixed thread height for now — adjust this value to taste. */
.ask-thread {
  height: 360px;
  overflow-y: auto;
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.ask-empty {
  margin: auto;
  text-align: center;
  color: var(--muted);
  font-size: 14px;
}
.ask-msg {
  max-width: 88%;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.ask-msg--user {
  align-self: flex-end;
  align-items: flex-end;
}
.ask-msg--bot {
  align-self: flex-start;
  align-items: flex-start;
}
.ask-msg__who {
  font-size: 11px;
  color: var(--muted);
  letter-spacing: 0.04em;
}
.ask-msg__body {
  padding: 12px 15px;
  border-radius: 14px;
  font-size: 15px;
  line-height: 1.6;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  border: 1px solid var(--hair);
}
.ask-msg--user .ask-msg__body {
  background: color-mix(in srgb, var(--p) 18%, transparent);
  border-top-right-radius: 4px;
}
.ask-msg--bot .ask-msg__body {
  background: color-mix(in srgb, var(--bg) 70%, #12253a 30%);
  border-top-left-radius: 4px;
}
.ask-card {
  align-self: flex-start;
  max-width: 88%;
  border: 1px solid var(--hair);
  border-radius: 14px;
  padding: 12px 15px;
  background: color-mix(in srgb, var(--bg) 70%, #12253a 30%);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.ask-card__title {
  font-weight: 600;
  font-size: 14px;
}
.ask-card__meta {
  font-size: 12px;
  color: var(--muted);
}
.ask-card__actions {
  display: flex;
  gap: 8px;
  margin-top: 4px;
}
.ask-cardbtn {
  border: 1px solid var(--hair);
  border-radius: 10px;
  padding: 8px 14px;
  font-size: 13px;
  cursor: pointer;
  background: var(--p);
  color: var(--bg);
  font-weight: 600;
}
.ask-cardbtn--ghost {
  background: transparent;
  color: var(--text);
}
.ask-cardbtn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.ask-speaking {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: var(--a);
  padding: 0 18px 10px;
  font-size: 13px;
}

.ask-input {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px;
  border-top: 1px solid var(--hair);
}
.ask-field {
  flex: 1;
  min-width: 0;
  background: color-mix(in srgb, var(--bg) 70%, #12253a 30%);
  border: 1px solid color-mix(in srgb, var(--p) 38%, transparent);
  border-radius: 12px;
  color: var(--text);
  font-size: 15px;
  padding: 12px 14px;
  outline: none;
}
.ask-field::placeholder {
  color: var(--muted);
}
.ask-field:focus {
  border-color: var(--p);
}
.ask-send {
  border: 0;
  border-radius: 12px;
  background: var(--p);
  color: var(--bg);
  font-weight: 700;
  font-size: 14px;
  padding: 12px 20px;
  cursor: pointer;
}
.ask-icon {
  width: 42px;
  height: 42px;
  flex: 0 0 auto;
  border: 1px solid color-mix(in srgb, var(--p) 38%, transparent);
  border-radius: 12px;
  background: color-mix(in srgb, var(--bg) 70%, #12253a 30%);
  color: var(--muted);
  font-size: 12px;
  cursor: pointer;
}
.ask-icon[aria-pressed="true"] {
  color: var(--a);
  border-color: color-mix(in srgb, var(--a) 58%, transparent);
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
}
`;

/** Floating Ask Artemis chat with manual focus trap and streaming status regions. */
export function AskPopup({ isOpen, onClose, onVoiceTrigger }: AskPopupProps) {
  const titleId = useId();
  const inputId = useId();
  const panelRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const threadRef = useRef<HTMLDivElement | null>(null);
  const [text, setText] = useState("");
  const snapshot = useAskStore((current) => current);

  useEffect(() => {
    if (!isOpen) return;
    window.requestAnimationFrame(() => inputRef.current?.focus());
  }, [isOpen]);

  useEffect(() => {
    const thread = threadRef.current;
    if (thread !== null) thread.scrollTop = thread.scrollHeight;
  }, [snapshot.messages, snapshot.streaming]);

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
    const pending = text.trim();
    if (pending === "") return;
    setText("");
    void askStore.send(pending);
  };

  const onMic = (): void => {
    void onVoiceTrigger?.({ speak: !snapshot.muted });
  };

  const messages = snapshot.messages;
  const lastBot = [...messages].reverse().find((message) => message.role === "assistant");
  const engineTag = lastBot?.engine ?? "local";
  const isEmpty = messages.length === 0 && snapshot.streaming === "";

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
            className="ask-panel"
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            onKeyDown={onKeyDown}
          >
            <header className="ask-header">
              <span className="ask-dot" aria-hidden="true" />
              <h2 id={titleId} className="ask-title">
                Ask Artemis
              </h2>
              {snapshot.buildMode ? <span className="ask-chip">Building capability</span> : null}
              <span className="ask-engine">{engineTag}</span>
              <button
                className="ask-close"
                type="button"
                aria-label="Close Ask Artemis"
                onClick={onClose}
              >
                ×
              </button>
            </header>

            <div className="ask-thread" ref={threadRef} aria-label="Conversation">
              {isEmpty ? (
                <p className="ask-empty">Ask me anything to get started.</p>
              ) : (
                messages.map((message) => {
                  const isUser = message.role === "user";
                  const body =
                    !isUser && message.text === "" ? snapshot.streaming : message.text;
                  if (message.kind === "plan" && message.plan !== undefined) {
                    const plan = message.plan;
                    return (
                      <div key={message.id} className="ask-msg ask-msg--bot">
                        <span className="ask-msg__who">Artemis</span>
                        <div className="ask-card">
                          <div className="ask-card__title">{plan.name}</div>
                          <div>{plan.summary}</div>
                          {plan.secrets.length > 0 ? (
                            <div className="ask-card__meta">Secrets: {plan.secrets.join(", ")}</div>
                          ) : null}
                          {plan.blocked ? (
                            <div className="ask-card__meta">{plan.block_reason}</div>
                          ) : null}
                          <div className="ask-card__actions">
                            <button
                              className="ask-cardbtn"
                              type="button"
                              disabled={plan.blocked}
                              onClick={() => void askStore.confirmBuild(message.buildId!)}
                            >
                              Build it
                            </button>
                            <button
                              className="ask-cardbtn ask-cardbtn--ghost"
                              type="button"
                              onClick={() => askStore.cancelBuild()}
                            >
                              Adjust
                            </button>
                          </div>
                        </div>
                      </div>
                    );
                  }
                  if (message.kind === "status") {
                    return (
                      <div key={message.id} className="ask-msg ask-msg--bot">
                        <span className="ask-msg__who">Artemis</span>
                        <div className="ask-card">
                          <div className="ask-card__meta">{message.text}</div>
                        </div>
                      </div>
                    );
                  }
                  if (message.kind === "result" && message.result !== undefined) {
                    const result = message.result;
                    return (
                      <div key={message.id} className="ask-msg ask-msg--bot">
                        <span className="ask-msg__who">Artemis</span>
                        <div className="ask-card">
                          <div className="ask-card__title">
                            {result.passed ? "✓ Verified" : result.blocked ? "Build blocked" : "Build failed"}
                          </div>
                          {result.output !== "" ? (
                            <div className="ask-card__meta">{result.output}</div>
                          ) : null}
                          {result.passed ? (
                            <div className="ask-card__actions">
                              <button
                                className="ask-cardbtn"
                                type="button"
                                onClick={() => void askStore.promoteBuild(message.buildId!)}
                              >
                                Add to my capabilities
                              </button>
                              <button
                                className="ask-cardbtn ask-cardbtn--ghost"
                                type="button"
                                onClick={() => askStore.cancelBuild()}
                              >
                                Discard
                              </button>
                            </div>
                          ) : null}
                        </div>
                      </div>
                    );
                  }
                  return (
                    <div
                      key={message.id}
                      className={`ask-msg ${isUser ? "ask-msg--user" : "ask-msg--bot"}`}
                    >
                      <span className="ask-msg__who">{isUser ? "You" : "Artemis"}</span>
                      <div className="ask-msg__body">
                        {message.failedLocked ? "Vault locked." : body}
                      </div>
                    </div>
                  );
                })
              )}
            </div>

            {snapshot.speaking ? (
              <span className="ask-speaking" aria-live="polite">
                Speaking
              </span>
            ) : null}

            <form className="ask-input" onSubmit={onSubmit}>
              <button className="ask-icon" type="button" aria-label="Hold to talk" onClick={onMic}>
                mic
              </button>
              <label className="ask-sr" htmlFor={inputId}>
                Ask Artemis
              </label>
              <input
                ref={inputRef}
                id={inputId}
                className="ask-field"
                value={text}
                onChange={(event) => setText(event.currentTarget.value)}
                aria-label="Ask Artemis"
                placeholder="Ask Artemis anything..."
                autoComplete="off"
              />
              <button
                className="ask-icon"
                type="button"
                aria-label={snapshot.muted ? "Muted" : "Speak answers"}
                aria-pressed={snapshot.muted}
                onClick={askStore.toggleMute}
              >
                {snapshot.muted ? "off" : "spk"}
              </button>
              <button className="ask-send" type="submit" aria-label="Send">
                Send
              </button>
            </form>

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
