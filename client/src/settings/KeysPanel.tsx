import { type CSSProperties, type FormEvent, useCallback, useEffect, useState } from "react";

import { blessClear, blessList, type BlessEntry } from "../api/bless";
import * as gateway from "../api/gateway";
import * as oauth from "../api/oauth";

export interface KeysPanelProps {
  open: boolean;
  onClose: () => void;
  pendingKey?: string;
  reconnectGoogle?: boolean;
}

const DEFAULT_GOOGLE_SCOPE = "https://www.googleapis.com/auth/calendar.readonly";

const styles = {
  backdrop: {
    position: "fixed",
    inset: 0,
    display: "grid",
    placeItems: "center",
    padding: 20,
    background: "rgba(0, 0, 0, 0.36)",
    zIndex: 20,
  },
  panel: {
    width: "min(460px, 100%)",
    maxHeight: "min(620px, calc(100vh - 40px))",
    overflow: "auto",
    border: "1px solid rgba(255, 255, 255, 0.18)",
    borderRadius: 8,
    background: "#12151c",
    color: "#f4f7fb",
    boxShadow: "0 18px 42px rgba(0, 0, 0, 0.38)",
  },
  header: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    padding: "16px 18px 12px",
    borderBottom: "1px solid rgba(255, 255, 255, 0.12)",
  },
  title: {
    margin: 0,
    fontSize: 18,
    fontWeight: 700,
  },
  spacer: {
    flex: 1,
  },
  body: {
    display: "grid",
    gap: 18,
    padding: 18,
  },
  sectionTitle: {
    margin: "0 0 8px",
    fontSize: 13,
    fontWeight: 700,
    color: "#cbd4e4",
  },
  list: {
    display: "grid",
    gap: 8,
    margin: 0,
    padding: 0,
    listStyle: "none",
  },
  row: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    padding: "10px 12px",
    border: "1px solid rgba(255, 255, 255, 0.12)",
    borderRadius: 6,
    background: "rgba(255, 255, 255, 0.04)",
  },
  keyName: {
    flex: 1,
    overflowWrap: "anywhere",
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
    fontSize: 13,
  },
  form: {
    display: "grid",
    gap: 10,
  },
  label: {
    display: "grid",
    gap: 5,
    fontSize: 12,
    color: "#d9e0ec",
  },
  input: {
    width: "100%",
    boxSizing: "border-box",
    border: "1px solid rgba(255, 255, 255, 0.2)",
    borderRadius: 6,
    background: "#0b0d12",
    color: "#f4f7fb",
    padding: "9px 10px",
    fontSize: 14,
  },
  valueRow: {
    display: "grid",
    gridTemplateColumns: "1fr auto",
    gap: 8,
  },
  actions: {
    display: "flex",
    justifyContent: "flex-end",
    gap: 8,
  },
  button: {
    border: "1px solid rgba(255, 255, 255, 0.22)",
    borderRadius: 6,
    background: "rgba(255, 255, 255, 0.08)",
    color: "#f4f7fb",
    padding: "8px 11px",
    fontSize: 13,
    cursor: "pointer",
  },
  primaryButton: {
    border: "1px solid #84a9ff",
    borderRadius: 6,
    background: "#84a9ff",
    color: "#0b0d12",
    padding: "8px 12px",
    fontSize: 13,
    fontWeight: 700,
    cursor: "pointer",
  },
  subtle: {
    margin: 0,
    color: "#aeb8c8",
    fontSize: 13,
    lineHeight: 1.4,
  },
  error: {
    margin: 0,
    color: "#ffb4b4",
    fontSize: 13,
  },
  success: {
    margin: 0,
    color: "#bdecc8",
    fontSize: 13,
    lineHeight: 1.4,
  },
} satisfies Record<string, CSSProperties>;

export function KeysPanel({ open, onClose, pendingKey, reconnectGoogle = false }: KeysPanelProps) {
  const [names, setNames] = useState<string[]>([]);
  const [blessed, setBlessed] = useState<BlessEntry[]>([]);
  const [googleStatus, setGoogleStatus] = useState<oauth.OAuthStatusResponse | null>(null);
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [googleScopes, setGoogleScopes] = useState(DEFAULT_GOOGLE_SCOPE);
  const [revealed, setRevealed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [connectingGoogle, setConnectingGoogle] = useState(false);
  const [disconnectingGoogle, setDisconnectingGoogle] = useState(false);
  const [deletingName, setDeletingName] = useState<string | null>(null);
  const [revokingName, setRevokingName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [googleMessage, setGoogleMessage] = useState<string | null>(null);
  const [googleConsentUrl, setGoogleConsentUrl] = useState<string | null>(null);

  const refresh = useCallback(async (): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      const [nextNames, nextBlessed, nextGoogleStatus] = await Promise.all([
        gateway.secretList(),
        blessList(),
        oauth.oauthStatus(),
      ]);
      setNames(nextNames);
      setBlessed(nextBlessed.filter((entry) => entry.blessed));
      setGoogleStatus(nextGoogleStatus);
    } catch (_error: unknown) {
      setError("Unable to load saved keys.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    setName(pendingKey ?? "");
    setValue("");
    setRevealed(false);
    void refresh();
  }, [open, pendingKey, refresh]);

  if (!open) return null;

  const submit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    const trimmed = name.trim();
    if (trimmed === "" || value === "") return;
    setSaving(true);
    setError(null);
    try {
      await gateway.secretSet(trimmed, value);
      setName("");
      setValue("");
      setRevealed(false);
      await refresh();
    } catch (_error: unknown) {
      setError("Unable to save key.");
    } finally {
      setSaving(false);
    }
  };

  const deleteSecret = async (secretName: string): Promise<void> => {
    setDeletingName(secretName);
    setError(null);
    try {
      await gateway.secretDelete(secretName);
      await refresh();
    } catch (_error: unknown) {
      setError("Unable to delete key.");
    } finally {
      setDeletingName(null);
    }
  };

  const connectGoogle = async (): Promise<void> => {
    const scopes = googleScopes
      .split(/[\s,]+/)
      .map((scope) => scope.trim())
      .filter((scope) => scope !== "");
    if (scopes.length === 0) return;
    setConnectingGoogle(true);
    setError(null);
    setGoogleMessage(null);
    setGoogleConsentUrl(null);
    try {
      const response = await oauth.oauthConnect(scopes);
      if ("status" in response && response.status === "client_not_configured") {
        setGoogleMessage("Add your Google client ID/secret above first.");
        return;
      }
      setGoogleMessage("A browser window opened - approve access, then Refresh.");
      if ("consent_url" in response) {
        setGoogleConsentUrl(response.consent_url);
      }
    } catch (_error: unknown) {
      setError("Unable to start Google connect.");
    } finally {
      setConnectingGoogle(false);
    }
  };

  const disconnectGoogle = async (): Promise<void> => {
    setDisconnectingGoogle(true);
    setError(null);
    setGoogleMessage(null);
    setGoogleConsentUrl(null);
    try {
      await oauth.oauthDisconnect(googleStatus?.account);
      await refresh();
    } catch (_error: unknown) {
      setError("Unable to disconnect Google.");
    } finally {
      setDisconnectingGoogle(false);
    }
  };

  const revokeBless = async (capabilityName: string): Promise<void> => {
    setRevokingName(capabilityName);
    setError(null);
    try {
      await blessClear(capabilityName);
      await refresh();
    } catch (_error: unknown) {
      setError("Unable to revoke Telegram access.");
    } finally {
      setRevokingName(null);
    }
  };

  return (
    <div style={styles.backdrop}>
      <section
        aria-labelledby="keys-panel-title"
        aria-modal="true"
        role="dialog"
        style={styles.panel}
      >
        <header style={styles.header}>
          <h2 id="keys-panel-title" style={styles.title}>
            Keys
          </h2>
          <span style={styles.spacer} />
          <button type="button" onClick={onClose} style={styles.button}>
            Close
          </button>
        </header>
        <div style={styles.body}>
          {pendingKey !== undefined && pendingKey !== "" && (
            <p style={styles.subtle}>Required key: {pendingKey}</p>
          )}
          {error !== null && <p style={styles.error}>{error}</p>}
          <section>
            <h3 style={styles.sectionTitle}>Saved keys</h3>
            {loading ? <p style={styles.subtle}>Loading keys...</p> : null}
            {!loading && names.length === 0 ? <p style={styles.subtle}>No keys saved.</p> : null}
            <ul style={styles.list}>
              {names.map((secretName) => (
                <li key={secretName} style={styles.row}>
                  <span style={styles.keyName}>{secretName}</span>
                  <button
                    type="button"
                    aria-label={`Delete ${secretName}`}
                    disabled={deletingName === secretName}
                    onClick={() => void deleteSecret(secretName)}
                    style={styles.button}
                  >
                    Delete
                  </button>
                </li>
              ))}
            </ul>
          </section>
          <section>
            <h3 style={styles.sectionTitle}>Telegram allowed capabilities</h3>
            {loading ? <p style={styles.subtle}>Loading capabilities...</p> : null}
            {!loading && blessed.length === 0 ? (
              <p style={styles.subtle}>No capabilities allowed.</p>
            ) : null}
            <ul style={styles.list}>
              {blessed.map((entry) => (
                <li key={entry.name} style={styles.row}>
                  <span style={styles.keyName}>
                    {entry.name}{" "}
                    <span style={styles.subtle}>
                      v{entry.blessed_version ?? entry.current_version ?? "-"}
                    </span>
                  </span>
                  <button
                    type="button"
                    aria-label={`Revoke ${entry.name}`}
                    disabled={revokingName === entry.name}
                    onClick={() => void revokeBless(entry.name)}
                    style={styles.button}
                  >
                    Revoke
                  </button>
                </li>
              ))}
            </ul>
          </section>
          <section>
            <h3 style={styles.sectionTitle}>Connect Google account</h3>
            {reconnectGoogle ? (
              <p style={styles.error}>Reconnect Google before running Google-backed capabilities.</p>
            ) : null}
            {googleMessage !== null && <p style={styles.success}>{googleMessage}</p>}
            {googleConsentUrl !== null && (
              <p style={styles.subtle}>
                Fallback URL: <span style={styles.keyName}>{googleConsentUrl}</span>
              </p>
            )}
            <label style={styles.label}>
              Google OAuth scopes
              <input
                autoComplete="off"
                name="google-oauth-scopes"
                onChange={(event) => setGoogleScopes(event.currentTarget.value)}
                style={styles.input}
                type="text"
                value={googleScopes}
              />
            </label>
            <div style={styles.actions}>
              <button type="button" onClick={() => void refresh()} style={styles.button}>
                Refresh
              </button>
              <button
                type="button"
                disabled={connectingGoogle}
                onClick={() => void connectGoogle()}
                style={styles.primaryButton}
              >
                Connect
              </button>
            </div>
            {loading ? <p style={styles.subtle}>Loading Google status...</p> : null}
            {googleStatus?.connected ? (
              <div style={styles.row}>
                <span style={styles.keyName}>
                  Connected: {googleStatus.account}
                  {googleStatus.granted_scopes.length > 0 ? (
                    <span style={styles.subtle}>
                      {" "}
                      ({googleStatus.granted_scopes.join(", ")})
                    </span>
                  ) : null}
                </span>
                <button
                  type="button"
                  aria-label={`Disconnect ${googleStatus.account}`}
                  disabled={disconnectingGoogle}
                  onClick={() => void disconnectGoogle()}
                  style={styles.button}
                >
                  Disconnect
                </button>
              </div>
            ) : (
              <p style={styles.subtle}>No Google account connected.</p>
            )}
          </section>
          <form onSubmit={(event) => void submit(event)} style={styles.form}>
            <h3 style={styles.sectionTitle}>Add key</h3>
            <label style={styles.label}>
              Key name
              <input
                autoComplete="off"
                name="secret-name"
                onChange={(event) => setName(event.currentTarget.value)}
                style={styles.input}
                type="text"
                value={name}
              />
            </label>
            <label style={styles.label}>
              Secret value
              <span style={styles.valueRow}>
                <input
                  autoComplete="off"
                  name="secret-value"
                  onChange={(event) => setValue(event.currentTarget.value)}
                  style={styles.input}
                  type={revealed ? "text" : "password"}
                  value={value}
                />
                <button
                  aria-label={revealed ? "Hide secret value" : "Show secret value"}
                  type="button"
                  onClick={() => setRevealed((current) => !current)}
                  style={styles.button}
                >
                  {revealed ? "Hide" : "Show"}
                </button>
              </span>
            </label>
            <div style={styles.actions}>
              <button type="submit" disabled={saving} style={styles.primaryButton}>
                Add
              </button>
            </div>
          </form>
        </div>
      </section>
    </div>
  );
}
