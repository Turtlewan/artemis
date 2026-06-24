import { useState } from "react";

import * as gateway from "../api/gateway";
import type { DomainDetailProps } from "../card/types";
import { connectionStore, useConnection } from "../state/connection";
import { EngineTagText } from "./DomainDetailShell";

interface StatusDetailProps extends DomainDetailProps {
  lockAction?: () => Promise<unknown>;
  logoutAction?: () => Promise<unknown>;
}

/** Status is connection chrome and intentionally works while the vault is locked. */
export function StatusDetail({
  onClose,
  lockAction = gateway.lock,
  logoutAction = gateway.logout,
}: StatusDetailProps) {
  const connection = useConnection();
  const [message, setMessage] = useState("");

  const lockNow = async (): Promise<void> => {
    await lockAction();
    connectionStore.onLocked();
    setMessage("Vault locked.");
  };

  const signOut = async (): Promise<void> => {
    await logoutAction();
    connectionStore.onRevoked();
    setMessage("Signed out.");
  };

  return (
    <section className="screen-shell" aria-labelledby="status-detail-title">
      <div className="screen-shell__head">
        <h2 id="status-detail-title" className="screen-shell__title">
          Status
        </h2>
        <div className="screen-shell__engine">
          <EngineTagText value="local" />
        </div>
      </div>
      <div className="screen-shell__scroll" tabIndex={0} aria-label="Status details">
        <dl>
          <dt>Connection</dt>
          <dd>{connection.state}</dd>
          <dt>Vault</dt>
          <dd>{connection.state === "unlocked" ? "Unlocked" : "Locked or unavailable"}</dd>
          <dt>Idle lock</dt>
          <dd>Local policy active</dd>
          <dt>This device</dt>
          <dd>Paired Artemis client</dd>
        </dl>
        <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
          <button className="screen-btn" type="button" onClick={() => void lockNow()}>
            Lock now
          </button>
          <button className="screen-btn" type="button" onClick={() => void signOut()}>
            Disconnect / Sign out
          </button>
          <button className="screen-btn" type="button" onClick={onClose}>
            Close
          </button>
        </div>
        <p role="status" aria-live="polite" className="screen-status">
          {message}
        </p>
      </div>
    </section>
  );
}
