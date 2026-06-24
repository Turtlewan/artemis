import { useMemo, useState } from "react";

import type { DomainDetailProps } from "../card/types";
import { DomainDetailShell, EngineTagText } from "./DomainDetailShell";
import type { GmailRead } from "./dtos";
import { useDomainRead, type DomainReader } from "./useDomainRead";

interface GmailDetailProps extends DomainDetailProps {
  reader?: DomainReader<GmailRead>;
}

export function GmailDetail({ domainId, onClose, reader }: GmailDetailProps) {
  const { data, loading, error } = useDomainRead<GmailRead>(domainId, reader);
  const [query, setQuery] = useState("");
  const [readerId, setReaderId] = useState<string | null>(null);
  const selected = [...(data?.needsYou ?? []), ...(data?.signal ?? [])].find((item) => item.id === readerId);
  const signal = useMemo(
    () => (data?.signal ?? []).filter((item) => item.subject.toLowerCase().includes(query.toLowerCase())),
    [data?.signal, query],
  );

  return (
    <DomainDetailShell
      domainId={domainId}
      title="Gmail"
      engine={<EngineTagText value="codex" />}
      loading={loading}
      error={error}
      empty={data !== null && data.needsYou.length + data.signal.length === 0 ? "No signal mail." : null}
      onClose={onClose}
    >
      {data !== null && (
        <div className="screen-split">
          <div>
            <h3 className="screen-eyebrow">Needs you</h3>
            <ul className="screen-list" role="list">
              {data.needsYou.map((mail) => (
                <li className="screen-row" key={mail.id}>
                  <button className="screen-btn" type="button" onClick={() => setReaderId(mail.id)}>
                    {mail.sender} - {mail.subject}
                  </button>
                  <p className="screen-muted">{mail.why}</p>
                  <button className="screen-btn" type="button">
                    Accept task suggestion
                  </button>{" "}
                  <button className="screen-btn" type="button">
                    Approve held event
                  </button>
                </li>
              ))}
            </ul>
            <h3 className="screen-eyebrow">Signal mail</h3>
            <input
              aria-label="Search signal mail"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              style={{ width: "100%", marginBottom: 8 }}
            />
            <ul className="screen-list" role="list">
              {signal.map((mail) => (
                <li className="screen-row" key={mail.id}>
                  <button className="screen-btn" type="button" onClick={() => setReaderId(mail.id)}>
                    {mail.sender} - {mail.subject}
                  </button>
                  <span className="screen-muted"> {mail.ts}</span>
                </li>
              ))}
            </ul>
          </div>
          <aside aria-label="Mail reader">
            <h3>Reader</h3>
            {selected === undefined ? (
              <p className="screen-muted">Select a message.</p>
            ) : (
              <>
                <strong>{selected.subject}</strong>
                <p className="screen-muted">{selected.sender}</p>
                <p>Spotlighted reader preview for {selected.subject}.</p>
                <a href={`https://mail.google.com/mail/u/0/#search/${encodeURIComponent(selected.subject)}`}>
                  Open in Gmail
                </a>
              </>
            )}
          </aside>
        </div>
      )}
    </DomainDetailShell>
  );
}
