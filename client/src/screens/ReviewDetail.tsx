import { useEffect, useState } from "react";

import * as gateway from "../api/gateway";
import type { ReviewItem } from "../api/dto";
import { toApiError } from "../api/errors";
import type { DomainDetailProps } from "../card/types";
import { connectionStore } from "../state/connection";
import { DomainDetailShell, EngineTagText } from "./DomainDetailShell";
import type { PendingAction } from "./dtos";

interface ReviewDetailProps extends DomainDetailProps {
  reader?: () => Promise<ReviewItem[]>;
  autoReader?: () => Promise<boolean>;
  approve?: (name: string) => Promise<unknown>;
  reject?: (name: string) => Promise<unknown>;
  actionsReader?: () => Promise<PendingAction[]>;
  actionApprove?: (id: string) => Promise<unknown>;
  actionReject?: (id: string) => Promise<unknown>;
}

const titleOf = (item: ReviewItem): string => item.name;
const engineOf = (item: ReviewItem): "local" | "codex" | "review" =>
  item.action_class === "external" ? "review" : item.safety === "auto" ? "local" : "codex";

const expiresSoon = (expiresAt: string): boolean => {
  const expires = Date.parse(expiresAt);
  return Number.isFinite(expires) && expires - Date.now() < 60 * 60 * 1000;
};

const actionCaption = (action: PendingAction): string => `${action.module}.${action.tool}`;

export function ReviewDetail({
  domainId,
  onClose,
  reader = gateway.reviewPending,
  autoReader = gateway.reviewAutoEnabled,
  approve = gateway.reviewApprove,
  reject = gateway.reviewReject,
  actionsReader = gateway.actionsPending,
  actionApprove = gateway.actionApprove,
  actionReject = gateway.actionReject,
}: ReviewDetailProps) {
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [actions, setActions] = useState<PendingAction[]>([]);
  const [autoEnabled, setAutoEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");

  useEffect(() => {
    let alive = true;
    Promise.all([actionsReader(), reader(), autoReader()])
      .then(([pendingActions, pending, auto]) => {
        if (!alive) return;
        setActions(pendingActions);
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
  }, [actionsReader, autoReader, reader]);

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

  const actOnPendingAction = async (action: PendingAction, kind: "approve" | "reject"): Promise<void> => {
    const before = actions;
    setActions((current) => current.filter((candidate) => candidate.id !== action.id));
    try {
      await (kind === "approve" ? actionApprove(action.id) : actionReject(action.id));
      setAnnouncement(kind === "approve" ? "Action approved." : "Action rejected.");
    } catch (error_: unknown) {
      setActions(before);
      const apiError = toApiError(error_);
      if (apiError.kind === "vaultLocked") {
        connectionStore.onLocked();
        setAnnouncement("Vault locked - re-authentication required.");
      } else if (apiError.kind === "http" && (apiError.status === 404 || apiError.status === 409)) {
        setAnnouncement("Pending action changed before review. Refresh and try again.");
      } else {
        setAnnouncement(kind === "approve" ? "Approval failed - reverted." : "Rejection failed - reverted.");
      }
    }
  };

  const empty =
    !loading && error === null && actions.length === 0 && items.length === 0 ? "Nothing waiting for your review." : null;

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
      <h3 className="screen-eyebrow">Pending actions</h3>
      {actions.length === 0 ? (
        <p className="screen-status">No pending actions.</p>
      ) : (
        <ul className="screen-list" role="list">
          {actions.map((action) => (
            <PendingActionRow
              action={action}
              key={action.id}
              onApprove={() => void actOnPendingAction(action, "approve")}
              onReject={() => void actOnPendingAction(action, "reject")}
            />
          ))}
        </ul>
      )}
      <h3 className="screen-eyebrow">Recipe review</h3>
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
      <p className="screen-muted">Calendar external effects and recipe changes wait here for approval.</p>
    </DomainDetailShell>
  );
}

function PendingActionRow({
  action,
  onApprove,
  onReject,
}: {
  action: PendingAction;
  onApprove: () => void;
  onReject: () => void;
}) {
  return (
    <li className="screen-row">
      <div style={{ display: "flex", gap: 10, alignItems: "start" }}>
        <div style={{ flex: 1 }}>
          <strong>{action.summary}</strong>
          <p className="screen-muted" style={{ margin: "4px 0" }}>
            {actionCaption(action)}
          </p>
          <p className="screen-muted" style={{ margin: "4px 0" }}>
            Expires {action.expires_at}
          </p>
          {expiresSoon(action.expires_at) ? (
            <span className="screen-pill" aria-label={`Expires soon: ${action.summary}`}>
              ! expires soon
            </span>
          ) : null}{" "}
          <span className="screen-pill">{action.status}</span>{" "}
          <span className="screen-pill">{action.action_class}</span>
        </div>
        <button
          className="screen-btn"
          type="button"
          aria-label={`Approve: ${action.summary}`}
          onClick={onApprove}
          style={{ minHeight: 44 }}
        >
          Approve
        </button>
        <button
          className="screen-btn"
          type="button"
          aria-label={`Reject: ${action.summary}`}
          onClick={onReject}
          style={{ minHeight: 44 }}
        >
          Reject
        </button>
      </div>
    </li>
  );
}
