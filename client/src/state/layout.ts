import type { LayoutDTO } from "../api/dto";
import { layoutGet, layoutPut } from "../api/gateway";

type Listener = () => void;

export interface LayoutSnapshot {
  layout: LayoutDTO;
  loading: boolean;
}

const defaultLayout = (): LayoutDTO => ({
  version: 1,
  updated_at: new Date(0).toISOString(),
  cards: [],
});

const listeners = new Set<Listener>();
let snapshot: LayoutSnapshot = {
  layout: defaultLayout(),
  loading: false,
};
let debounceTimer: ReturnType<typeof setTimeout> | null = null;

const emit = (): void => {
  for (const listener of listeners) {
    listener();
  }
};

const isNewerOrEqual = (candidate: LayoutDTO, current: LayoutDTO): boolean =>
  Date.parse(candidate.updated_at) >= Date.parse(current.updated_at);

const setSnapshot = (next: LayoutSnapshot): void => {
  snapshot = next;
  emit();
};

export const layoutStore = {
  getSnapshot: (): LayoutSnapshot => snapshot,
  subscribe: (listener: Listener): (() => void) => {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
  loadOnConnect: async (): Promise<void> => {
    setSnapshot({ ...snapshot, loading: true });
    const layout = await layoutGet();
    setSnapshot({ layout, loading: false });
  },
  setLocalLayout: (layout: LayoutDTO): void => {
    setSnapshot({ ...snapshot, layout });
  },
  saveAfterDragEnd: (layout: LayoutDTO, debounceMs = 250): void => {
    setSnapshot({ ...snapshot, layout });
    if (debounceTimer !== null) {
      clearTimeout(debounceTimer);
    }
    debounceTimer = setTimeout(() => {
      void layoutStore.flush(layout);
    }, debounceMs);
  },
  flush: async (layout = snapshot.layout): Promise<void> => {
    const response = await layoutPut(layout);
    if (isNewerOrEqual(response, snapshot.layout)) {
      setSnapshot({ ...snapshot, layout: response });
    }
  },
  resetToDefault: (): void => {
    const layout = { ...defaultLayout(), updated_at: new Date().toISOString() };
    layoutStore.saveAfterDragEnd(layout, 0);
  },
  resetForTest: (): void => {
    if (debounceTimer !== null) {
      clearTimeout(debounceTimer);
      debounceTimer = null;
    }
    setSnapshot({ layout: defaultLayout(), loading: false });
  },
};
