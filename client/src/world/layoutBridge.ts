import { useCallback, useEffect, useMemo, useState } from "react";

import type { CardPlacement, LayoutDTO } from "../api/dto";
import { layoutStore } from "../state/layout";

export interface LayoutBridge {
  placements: CardPlacement[];
  updatePlacement: (placement: CardPlacement, persist: boolean) => void;
  resetToDefault: () => void;
}

const layoutFromPlacements = (placements: CardPlacement[]): LayoutDTO => ({
  version: 1,
  updated_at: new Date().toISOString(),
  cards: placements,
});

// v2: the brain's capability-backed layout is the ONLY source of map nodes; no hardcoded
// client-side domain seed. An empty layout means an empty map (nothing has been built yet).
const validCards = (layout: LayoutDTO): CardPlacement[] => layout.cards;

/** Bridges world card positions to CLIENT-core's debounced, brain-synced layout store. */
export function useLayoutBridge(enabled = true): LayoutBridge {
  const [placements, setPlacements] = useState<CardPlacement[]>(() =>
    validCards(layoutStore.getSnapshot().layout),
  );

  useEffect(() => {
    if (!enabled) return undefined;
    let active = true;
    const sync = (): void => {
      if (active) setPlacements(validCards(layoutStore.getSnapshot().layout));
    };
    const unsubscribe = layoutStore.subscribe(sync);
    void layoutStore.loadOnConnect().catch(() => {
      if (active) setPlacements([]);
    });
    sync();
    return () => {
      active = false;
      unsubscribe();
    };
  }, [enabled]);

  const updatePlacement = useCallback((placement: CardPlacement, persist: boolean) => {
    setPlacements((current) => {
      const next = current.map((card) => (card.id === placement.id ? placement : card));
      if (persist) layoutStore.saveAfterDragEnd(layoutFromPlacements(next));
      return next;
    });
  }, []);

  const resetToDefault = useCallback(() => {
    const next: CardPlacement[] = [];
    setPlacements(next);
    layoutStore.saveAfterDragEnd(layoutFromPlacements(next), 0);
  }, []);

  return useMemo(
    () => ({ placements, updatePlacement, resetToDefault }),
    [placements, resetToDefault, updatePlacement],
  );
}

export const layoutBridgeTestApi = {
  layoutFromPlacements,
  validCards,
};
