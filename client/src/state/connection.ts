import { useSyncExternalStore } from "react";

import type { ConnectionState } from "../api/dto";

export interface ConnectionSnapshot {
  state: ConnectionState;
}

type Listener = () => void;

const listeners = new Set<Listener>();
let snapshot: ConnectionSnapshot = { state: "unpaired" };

const emit = (): void => {
  for (const listener of listeners) {
    listener();
  }
};

const setState = (state: ConnectionState): void => {
  snapshot = { state };
  emit();
};

export const connectionStore = {
  getSnapshot: (): ConnectionSnapshot => snapshot,
  subscribe: (listener: Listener): (() => void) => {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
  onPaired: (): void => {
    if (snapshot.state === "unpaired") {
      setState("disconnected");
    }
  },
  onConnected: (): void => {
    setState("connectedLocked");
  },
  onLocked: (): void => {
    if (snapshot.state === "unlocked") {
      setState("connectedLocked");
    }
  },
  onUnlocked: (): void => {
    if (snapshot.state === "connectedLocked") {
      setState("unlocked");
    }
  },
  onDisconnected: (): void => {
    setState("disconnected");
  },
  onRevoked: (): void => {
    setState("unpaired");
  },
  resetForTest: (): void => {
    setState("unpaired");
  },
};

export const useConnection = (): ConnectionSnapshot =>
  useSyncExternalStore(connectionStore.subscribe, connectionStore.getSnapshot);
