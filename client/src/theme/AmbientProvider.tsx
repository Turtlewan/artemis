import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { applyCell, resolveCell } from "./ambient";
import type { CellKey } from "./palettes";

const AmbientCellContext = createContext<CellKey | null>(null);

const nextMinuteDelay = (now: Date): number =>
  Math.max(250, (60 - now.getSeconds()) * 1_000 - now.getMilliseconds());

const useReducedMotion = (): boolean => {
  const [reduced, setReduced] = useState(() =>
    typeof window === "undefined"
      ? false
      : window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const listener = (event: MediaQueryListEvent): void => setReduced(event.matches);
    setReduced(query.matches);
    query.addEventListener("change", listener);
    return () => query.removeEventListener("change", listener);
  }, []);

  return reduced;
};

/** Applies ambient theme tokens to `:root` and exposes the active cell to descendants. */
export function AmbientProvider({ children }: { children: ReactNode }) {
  const [cell, setCell] = useState<CellKey>(() => resolveCell(new Date()));
  const reducedMotion = useReducedMotion();

  useEffect(() => {
    const root = document.documentElement;
    const previousTransition = root.style.transition;
    if (reducedMotion) root.style.transition = "none";
    applyCell(cell, root);
    if (reducedMotion) {
      window.requestAnimationFrame(() => {
        root.style.transition = previousTransition;
      });
    }
  }, [cell, reducedMotion]);

  useEffect(() => {
    let timer: number | undefined;
    const tick = (): void => {
      setCell(resolveCell(new Date()));
      timer = window.setTimeout(tick, nextMinuteDelay(new Date()));
    };
    tick();
    return () => {
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, []);

  const value = useMemo(() => cell, [cell]);
  return <AmbientCellContext.Provider value={value}>{children}</AmbientCellContext.Provider>;
}

/** Reads the current ambient cell from `AmbientProvider`. */
export const useAmbientCell = (): CellKey => {
  const cell = useContext(AmbientCellContext);
  if (cell === null) throw new Error("useAmbientCell must be used inside AmbientProvider");
  return cell;
};
