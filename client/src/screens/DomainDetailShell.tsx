import { useEffect, useId, useRef, type ReactNode } from "react";

import type { DomainId } from "../domains";
import { domainLabel } from "../domains";
import { useConnection } from "../state/connection";
import { LOCK_TIER } from "./domainRoutes";

interface DomainDetailShellProps {
  domainId: DomainId;
  title?: string;
  engine?: ReactNode;
  loading?: boolean;
  error?: string | null;
  empty?: string | null;
  onClose: () => void;
  children: ReactNode;
}

const styles = `
.screen-shell{height:100%;min-height:0;display:flex;flex-direction:column;color:var(--text)}
.screen-shell__head{display:flex;align-items:center;gap:12px;margin-bottom:12px}
.screen-shell__title{margin:0;font-size:18px;line-height:1.2;font-family:Space Grotesk,Inter,system-ui,sans-serif}
.screen-shell__engine{margin-left:auto;display:flex;align-items:center;gap:7px}
.screen-shell__scroll{min-height:0;flex:1;overflow:auto;scroll-padding-top:18px;padding-right:6px}
.screen-status{color:var(--muted);font-size:13px}
.screen-lock{border:1px solid var(--hair);border-radius:8px;padding:16px;background:color-mix(in srgb,var(--p) 7%,transparent)}
.screen-lock h3{margin:0 0 6px;font-size:15px}.screen-lock p{margin:0 0 12px;color:var(--muted)}
.screen-btn{min-width:24px;min-height:24px;border:1px solid var(--hair);border-radius:7px;background:transparent;color:var(--text);font:inherit;font-size:12px;padding:5px 10px;cursor:pointer}
.screen-btn:hover,.screen-btn:focus-visible{border-color:var(--focus-ring);background:color-mix(in srgb,var(--p) 10%,transparent)}
.engine-tag{font-family:Space Grotesk,Inter,system-ui,sans-serif;font-size:10px;letter-spacing:.12em;text-transform:uppercase;border:1px solid var(--hair);border-radius:999px;padding:2px 8px;color:var(--muted)}
.engine-tag--review{color:var(--a);border-color:color-mix(in srgb,var(--a) 45%,transparent)}
.screen-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px}
.screen-row{border-top:1px solid var(--hair);padding:9px 0}.screen-row:first-child{border-top:0}
.screen-eyebrow{font-family:Space Grotesk,Inter,system-ui,sans-serif;font-size:10px;letter-spacing:.18em;text-transform:uppercase;color:var(--muted);margin:14px 0 8px}
.screen-muted{color:var(--muted)}.screen-split{display:grid;grid-template-columns:minmax(0,1fr) minmax(220px,38%);gap:16px}
.screen-pill{display:inline-flex;align-items:center;gap:5px;border:1px solid var(--hair);border-radius:999px;padding:2px 8px;font-family:Space Grotesk,Inter,system-ui,sans-serif;font-size:10px;color:var(--muted)}
`;

let mounted = false;
const ensureStyles = (): void => {
  if (mounted || typeof document === "undefined") return;
  const style = document.createElement("style");
  style.dataset.screens = "true";
  style.textContent = styles;
  document.head.append(style);
  mounted = true;
};

export function EngineTagText({ value }: { value: "local" | "codex" | "review" }) {
  return <span className={`engine-tag engine-tag--${value}`}>{value}</span>;
}

/** Shared detail scaffold: title, labelled internal scroll, status states, and unlock gate. */
export function DomainDetailShell({
  domainId,
  title = domainLabel(domainId),
  engine,
  loading = false,
  error = null,
  empty = null,
  onClose,
  children,
}: DomainDetailShellProps) {
  ensureStyles();
  const headingId = useId();
  const unlockRef = useRef<HTMLButtonElement | null>(null);
  const previousFocus = useRef<HTMLElement | null>(
    typeof document === "undefined" ? null : document.activeElement instanceof HTMLElement ? document.activeElement : null,
  );
  const connection = useConnection();
  const locked = LOCK_TIER[domainId] === "unlocked" && connection.state === "connectedLocked";

  useEffect(() => {
    if (locked) unlockRef.current?.focus();
  }, [locked]);

  const closeLocked = (): void => {
    onClose();
    window.requestAnimationFrame(() => previousFocus.current?.focus());
  };

  return (
    <section className="screen-shell" aria-labelledby={headingId}>
      <div className="screen-shell__head">
        <h2 id={headingId} className="screen-shell__title">
          {title}
        </h2>
        {engine !== undefined && <div className="screen-shell__engine">{engine}</div>}
      </div>
      <div className="screen-shell__scroll" tabIndex={0} aria-label={`${title} details`}>
        {locked ? (
          <div className="screen-lock" role="status" aria-live="polite">
            <h3>Unlock required</h3>
            <p>Vault-locked. Re-unlock Artemis to view {title}.</p>
            <button ref={unlockRef} className="screen-btn" type="button" onClick={closeLocked}>
              Re-unlock
            </button>
          </div>
        ) : loading ? (
          <p className="screen-status" role="status" aria-live="polite">
            Loading {title}...
          </p>
        ) : error !== null ? (
          <p className="screen-status" role="status" aria-live="polite">
            {error}
          </p>
        ) : empty !== null ? (
          <p className="screen-status" role="status" aria-live="polite">
            {empty}
          </p>
        ) : (
          children
        )}
      </div>
    </section>
  );
}
