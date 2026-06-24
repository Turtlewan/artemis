import { useCallback, useEffect, useMemo, useState } from "react";

import type { CardPlacement, LayoutDTO } from "../api/dto";
import { layoutStore } from "../state/layout";
import { defaultPlacements } from "./clusters";

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

const validCards = (layout: LayoutDTO): CardPlacement[] =>
  layout.cards.length > 0 ? layout.cards : defaultPlacements();

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
      if (active) setPlacements(defaultPlacements());
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
    const next = defaultPlacements();
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
