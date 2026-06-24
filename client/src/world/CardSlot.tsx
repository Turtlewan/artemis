import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";

import type { CardPlacement } from "../api/dto";
import type { DomainId } from "../domains";
import { domainLabel } from "../domains";

export interface CardSlotProps {
  placement: CardPlacement;
  scale: number;
  onMove: (placement: CardPlacement, persist: boolean) => void;
  onOpen: (domain: DomainId) => void;
  children?: ReactNode;
}

const STEP = 48;
const clampPlacement = (placement: CardPlacement): CardPlacement => ({
  ...placement,
  x: Math.max(0, Math.min(2_600 - placement.w, placement.x)),
  y: Math.max(0, Math.min(1_760 - placement.h, placement.y)),
});

const asDomain = (domain: string): DomainId => domain as DomainId;

/** Native button slot for a future glance-card face, with pointer and keyboard repositioning. */
export function CardSlot({ placement, scale, onMove, onOpen, children }: CardSlotProps) {
  const [moving, setMoving] = useState(false);
  const [draft, setDraft] = useState<CardPlacement | null>(null);
  const dragRef = useRef<{ x: number; y: number; placement: CardPlacement; pointerId: number } | null>(null);
  const active = draft ?? placement;
  const domain = asDomain(placement.domain);

  useEffect(() => {
    if (!moving) setDraft(null);
  }, [moving]);

  useEffect(() => {
    const pointerMove = (event: globalThis.PointerEvent): void => {
      const drag = dragRef.current;
      if (drag === null || drag.pointerId !== event.pointerId) return;
      const next = clampPlacement({
        ...drag.placement,
        x: drag.placement.x + (event.clientX - drag.x) / scale,
        y: drag.placement.y + (event.clientY - drag.y) / scale,
      });
      onMove(next, false);
    };
    const pointerUp = (event: globalThis.PointerEvent): void => {
      const drag = dragRef.current;
      if (drag === null || drag.pointerId !== event.pointerId) return;
      dragRef.current = null;
      onMove(clampPlacement(placement), true);
    };
    window.addEventListener("pointermove", pointerMove);
    window.addEventListener("pointerup", pointerUp);
    return () => {
      window.removeEventListener("pointermove", pointerMove);
      window.removeEventListener("pointerup", pointerUp);
    };
  }, [onMove, placement, scale]);

  const startDrag = (event: PointerEvent<HTMLSpanElement>): void => {
    event.preventDefault();
    event.stopPropagation();
    dragRef.current = { x: event.clientX, y: event.clientY, placement, pointerId: event.pointerId };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const gripKey = (event: KeyboardEvent<HTMLSpanElement>): void => {
    if (!moving && event.key === "Enter") {
      event.preventDefault();
      setMoving(true);
      setDraft(placement);
      return;
    }
    if (!moving) return;
    const moves: Record<string, [number, number]> = {
      ArrowUp: [0, -STEP],
      ArrowDown: [0, STEP],
      ArrowLeft: [-STEP, 0],
      ArrowRight: [STEP, 0],
    };
    const move = moves[event.key];
    if (move !== undefined) {
      event.preventDefault();
      const next = clampPlacement({ ...active, x: active.x + move[0], y: active.y + move[1] });
      setDraft(next);
      onMove(next, false);
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      onMove(active, true);
      setMoving(false);
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      onMove(placement, false);
      setMoving(false);
    }
  };

  return (
    <button
      ref={(node) => {
        if (node !== null) node.dataset.cardSlot = placement.domain;
      }}
      type="button"
      className={`world-card glass${moving ? " world-card--moving" : ""}`}
      style={{
        left: `${active.x}px`,
        top: `${active.y}px`,
        width: `${active.w}px`,
        height: `${active.h}px`,
      }}
      aria-label={domainLabel(domain)}
      onClick={() => onOpen(domain)}
    >
      <span className="glass-sheen" />
      <span className="world-card__chrome">
        <span className="world-card__title">{domainLabel(domain)}</span>
        <span
          className="world-card__grip"
          tabIndex={0}
          role="button"
          aria-label={`Move ${domainLabel(domain)}`}
          aria-pressed={moving}
          onPointerDown={startDrag}
          onClick={(event) => event.stopPropagation()}
          onKeyDown={gripKey}
        >
          <span />
          <span />
          <span />
          <span />
          <span />
          <span />
        </span>
      </span>
      <span className="world-card__body">
        {children ?? <span className="world-card__placeholder">{placement.cluster}</span>}
      </span>
      {moving ? <span className="world-card__move-state">Move mode</span> : null}
    </button>
  );
}
