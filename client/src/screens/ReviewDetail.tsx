import { useEffect, useState } from "react";

import * as gateway from "../api/gateway";
import type { ReviewItem } from "../api/dto";
import type { DomainDetailProps } from "../card/types";
import { DomainDetailShell, EngineTagText } from "./DomainDetailShell";

interface ReviewDetailProps extends DomainDetailProps {
  reader?: () => Promise<ReviewItem[]>;
  autoReader?: () => Promise<boolean>;
  approve?: (name: string) => Promise<unknown>;
  reject?: (name: string) => Promise<unknown>;
}

const titleOf = (item: ReviewItem): string => item.name;
const engineOf = (item: ReviewItem): "local" | "codex" | "review" =>
  item.action_class === "external" ? "review" : item.safety === "auto" ? "local" : "codex";

export function ReviewDetail({
  domainId,
  onClose,
  reader = gateway.reviewPending,
  autoReader = gateway.reviewAutoEnabled,
  approve = gateway.reviewApprove,
  reject = gateway.reviewReject,
}: ReviewDetailProps) {
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [autoEnabled, setAutoEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");

  useEffect(() => {
    let alive = true;
    Promise.all([reader(), autoReader()])
      .then(([pending, auto]) => {
        if (!alive) return;
        setItems(pending);
        setAutoEnabled(auto);
        setError(null);
      })
      .catch(() => {
        if (alive) setError("Review data not yet available.");
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [autoReader, reader]);

  const act = async (item: ReviewItem, kind: "approve" | "reject"): Promise<void> => {
    const before = items;
    setItems((current) => current.filter((candidate) => candidate.name !== item.name));
    try {
      await (kind === "approve" ? approve(item.name) : reject(item.name));
      setAnnouncement(kind === "approve" ? "Recipe approved." : "Recipe rejected.");
    } catch {
      setItems(before);
      setAnnouncement(kind === "approve" ? "Approval failed - reverted." : "Rejection failed - reverted.");
    }
  };

  const empty = !loading && error === null && items.length === 0 ? "Nothing waiting for your review." : null;

  return (
    <DomainDetailShell
      domainId={domainId}
      title="Review"
      engine={<EngineTagText value="review" />}
      loading={loading}
      error={error}
      empty={empty}
      onClose={onClose}
    >
      <div role="status" aria-live="polite" className="screen-status">
        {announcement}
      </div>
      <p className="screen-muted">Auto recipes are {autoEnabled ? "enabled" : "paused"}.</p>
      <ul className="screen-list" role="list">
        {items.map((item) => (
          <li className="screen-row" key={item.name}>
            <div style={{ display: "flex", gap: 10, alignItems: "start" }}>
              <div style={{ flex: 1 }}>
                <strong>{titleOf(item)}</strong>
                <p className="screen-muted" style={{ margin: "4px 0" }}>
                  {item.description}
                </p>
                <p style={{ margin: "4px 0" }}>{item.explanation}</p>
                <span className="screen-pill">{item.status}</span>{" "}
                <span className="screen-pill">{item.action_class}</span>{" "}
                <EngineTagText value={engineOf(item)} />
              </div>
              <button
                className="screen-btn"
                type="button"
                aria-label={`Approve: ${titleOf(item)}`}
                onClick={() => void act(item, "approve")}
              >
                Approve
              </button>
              <button
                className="screen-btn"
                type="button"
                aria-label={`Reject: ${titleOf(item)}`}
                onClick={() => void act(item, "reject")}
              >
                Reject
              </button>
            </div>
          </li>
        ))}
      </ul>
      <h3 className="screen-eyebrow">Gate pending actions</h3>
      <p className="screen-muted">Calendar external effects and recipe changes wait here for approval.</p>
    </DomainDetailShell>
  );
}
