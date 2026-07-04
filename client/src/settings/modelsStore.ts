import { useSyncExternalStore } from "react";

export interface ModelsSnapshot {
  open: boolean;
}

type Listener = () => void;

const listeners = new Set<Listener>();
let snapshot: ModelsSnapshot = { open: false };

const emit = (): void => {
  for (const listener of listeners) listener();
};

const update = (next: ModelsSnapshot): void => {
  snapshot = next;
  emit();
};

export const openModels = (): void => {
  update({ open: true });
};

export const closeModels = (): void => {
  update({ open: false });
};

export const modelsStore = {
  getSnapshot: (): ModelsSnapshot => snapshot,
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

export const useModelsStore = <T,>(selector: (current: ModelsSnapshot) => T): T => {
  return useSyncExternalStore(
    modelsStore.subscribe,
    () => selector(modelsStore.getSnapshot()),
    () => selector(modelsStore.getSnapshot()),
  );
};
