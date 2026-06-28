import { useId, useRef, useState, type FormEvent, type ReactElement } from "react";

import type { ConnectionState } from "../api/dto";
import { pairDevice, type PairingError } from "./pairing";
import { recoverWithPassphrase } from "./recovery";

interface PairingScreenProps {
  state: ConnectionState;
}

type Phase = "idle" | "submitting";

const styles = `
.pair-gate{position:fixed;inset:0;z-index:4;display:grid;place-items:center;padding:24px;color:var(--text);background:transparent}
.pair-panel{width:min(100%,420px);padding:32px;display:flex;flex-direction:column;align-items:stretch;gap:18px}
.pair-mark{width:70px;height:70px;align-self:center;color:var(--p)}
.pair-title{margin:0;text-align:center;font-size:24px;line-height:1.1;font-family:Space Grotesk,Inter,system-ui,sans-serif;color:var(--text)}
.pair-form{display:flex;flex-direction:column;gap:12px}
.pair-field{display:flex;flex-direction:column;gap:7px;font-size:12px;font-family:Space Grotesk,Inter,system-ui,sans-serif;color:var(--muted);text-transform:uppercase;letter-spacing:.12em}
.pair-input{width:100%;box-sizing:border-box;border:1px solid var(--hair);border-radius:8px;background:color-mix(in srgb,var(--p) 6%,transparent);color:var(--text);font:16px/1.4 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;padding:11px 12px;outline:0}
.pair-input:focus{border-color:var(--p);box-shadow:0 0 0 1px color-mix(in srgb,var(--p) 34%,transparent),0 0 24px -14px var(--p)}
.pair-input:disabled{color:var(--muted)}
.pair-actions{display:flex;align-items:center;gap:10px}
.pair-button{min-height:38px;border:1px solid var(--hair);border-radius:8px;background:color-mix(in srgb,var(--p) 12%,transparent);color:var(--text);font:600 13px/1 Space Grotesk,Inter,system-ui,sans-serif;padding:0 16px;cursor:pointer}
.pair-button:hover,.pair-button:focus-visible{border-color:var(--p);background:color-mix(in srgb,var(--p) 18%,transparent)}
.pair-button:disabled{cursor:not-allowed;color:var(--muted);background:transparent}
.pair-hint{margin:0}.pair-hint code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:var(--text)}
.pair-error{margin:0;color:var(--text);border:1px solid var(--hair);border-radius:8px;padding:10px;background:color-mix(in srgb,var(--p) 7%,transparent)}
.pair-link{align-self:flex-start;border:0;background:transparent;color:var(--p);font:600 13px/1 Space Grotesk,Inter,system-ui,sans-serif;padding:4px 0;cursor:pointer}
.pair-recovery{display:flex;flex-direction:column;gap:10px;border-top:1px solid var(--hair);padding-top:14px}
@media (prefers-reduced-motion: no-preference){.pair-mark--pulse{animation:pair-pulse 1.4s ease-in-out infinite}@keyframes pair-pulse{50%{opacity:.54}}}
@media (prefers-reduced-motion: reduce){.pair-mark--pulse{animation:none}}
`;

const errorMessage = (err: PairingError): string => {
  switch (err.kind) {
    case "wrongOrExpiredCode":
      return "That code didn't work or has expired. Mint a new one and try again.";
    case "offTunnel":
      return "Can't reach your brain. Check the tunnel/connection.";
    case "biometricCancelled":
      return "Biometric check was cancelled. Try again.";
    case "network":
      return "Something went wrong reaching your brain. Try again.";
  }
};

const toPairingError = (error: unknown): PairingError =>
  typeof error === "object" &&
  error !== null &&
  "kind" in error &&
  ["wrongOrExpiredCode", "offTunnel", "biometricCancelled", "network"].includes(
    String(error.kind),
  )
    ? (error as PairingError)
    : { kind: "network" };

export function PairingScreen({ state }: PairingScreenProps): ReactElement {
  const codeId = useId();
  const passphraseId = useId();
  const [code, setCode] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<PairingError | null>(null);
  const [recoverOpen, setRecoverOpen] = useState(false);
  const [passphrase, setPassphrase] = useState("");
  const [status, setStatus] = useState("");
  const passphraseRef = useRef<HTMLInputElement | null>(null);
  const submitting = phase === "submitting";

  const onSubmit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    setPhase("submitting");
    setError(null);
    setStatus("Connecting…");
    try {
      await pairDevice(code.trim());
    } catch (e: unknown) {
      const pairingError = toPairingError(e);
      setError(pairingError);
      setPhase("idle");
      setStatus(errorMessage(pairingError));
    }
  };

  const onRecover = async (): Promise<void> => {
    setError(null);
    setStatus("Recovering...");
    try {
      await recoverWithPassphrase(passphrase);
      setStatus("Recovery request sent.");
    } catch (e: unknown) {
      const pairingError = toPairingError(e);
      setError(pairingError);
      setStatus(errorMessage(pairingError));
    } finally {
      setPassphrase("");
      passphraseRef.current?.focus();
    }
  };

  return (
    <div className="pair-gate">
      <style>{styles}</style>
      <span className="grid-mask" aria-hidden="true" />
      <section className="glass pair-panel" aria-labelledby="pair-title">
        <span className="glass-sheen" aria-hidden="true" />
        <svg
          className={`pair-mark glow-primary${submitting ? " pair-mark--pulse" : ""}`}
          viewBox="0 0 72 72"
          aria-hidden="true"
        >
          <circle cx="36" cy="36" r="29" fill="none" stroke="var(--p)" strokeWidth="1.6" />
          <circle cx="36" cy="36" r="18" fill="none" stroke="var(--p)" strokeWidth="1.4" />
          <path d="M36 8v11M36 53v11M8 36h11M53 36h11" fill="none" stroke="var(--p)" strokeWidth="1.4" />
          <path d="M23 23l-8-8M49 23l8-8M23 49l-8 8M49 49l8 8" fill="none" stroke="var(--p)" strokeWidth="1.2" />
        </svg>
        <h1 id="pair-title" className="pair-title">
          {state === "disconnected" ? "Reconnect" : "Pair this device"}
        </h1>
        <form className="pair-form" onSubmit={(event) => void onSubmit(event)}>
          <label className="pair-field" htmlFor={codeId}>
            Pairing code
            <input
              id={codeId}
              className="pair-input caret-primary"
              value={code}
              autoFocus
              autoComplete="off"
              spellCheck={false}
              inputMode="text"
              disabled={submitting}
              onChange={(event) => setCode(event.currentTarget.value)}
            />
          </label>
          <p className="screen-status pair-hint">
            Get a code on your brain: <code>POST /app/admin/pair-code</code> (valid 10 min)
          </p>
          {error === null ? (
            <p className="screen-status" role="status" aria-live="polite">
              {status}
            </p>
          ) : (
            <p role="alert" aria-live="assertive" className="screen-status pair-error">
              {errorMessage(error)}
            </p>
          )}
          <div className="pair-actions">
            <button className="pair-button" type="submit" disabled={submitting || code.trim() === ""}>
              {submitting ? "Connecting…" : state === "disconnected" ? "Connect" : "Pair"}
            </button>
          </div>
        </form>
        <button
          type="button"
          className="pair-link"
          aria-expanded={recoverOpen}
          onClick={() => setRecoverOpen((value) => !value)}
        >
          Recover with passphrase
        </button>
        {recoverOpen ? (
          <div className="pair-recovery">
            <label className="pair-field" htmlFor={passphraseId}>
              Recovery passphrase
              <input
                ref={passphraseRef}
                id={passphraseId}
                className="pair-input"
                type="password"
                value={passphrase}
                autoComplete="off"
                onChange={(event) => setPassphrase(event.currentTarget.value)}
              />
            </label>
            <button className="pair-button" type="button" onClick={() => void onRecover()}>
              Recover
            </button>
            <p className="screen-status">
              On this device, recovery is not yet available (Mac-gated).
            </p>
          </div>
        ) : null}
      </section>
    </div>
  );
}
