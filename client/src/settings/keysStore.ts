import { useSyncExternalStore } from "react";

export interface KeysSnapshot {
  open: boolean;
  pendingKey?: string;
}

type Listener = () => void;

const listeners = new Set<Listener>();
let snapshot: KeysSnapshot = { open: false };

const emit = (): void => {
  for (const listener of listeners) listener();
};

const update = (next: KeysSnapshot): void => {
  snapshot = next;
  emit();
};

export const openKeys = (pendingKey?: string): void => {
  update(pendingKey === undefined ? { open: true } : { open: true, pendingKey });
};

export const closeKeys = (): void => {
  update({ open: false });
};

export const keysStore = {
  getSnapshot: (): KeysSnapshot => snapshot,
  subscribe: (listener: Listener): (() => void) => {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
  resetForTest: (): void => {
    update({ open: false });
  },
};

export const useKeysStore = <T,>(selector: (current: KeysSnapshot) => T): T => {
  return useSyncExternalStore(
    keysStore.subscribe,
    () => selector(keysStore.getSnapshot()),
    () => selector(keysStore.getSnapshot()),
  );
};
