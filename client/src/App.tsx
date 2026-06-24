import { useCallback, useEffect, useState } from "react";

import type { CardPlacement } from "./api/dto";
import type { DomainId } from "./domains";
import { domainLabel } from "./domains";
import { useConnection } from "./state/connection";
import { AmbientProvider } from "./theme/AmbientProvider";
import { PhotoBackground } from "./theme/PhotoBackground";
import { Dock } from "./world/Dock";
import { useLayoutBridge } from "./world/layoutBridge";
import { Minimap } from "./world/Minimap";
import { useCamera, type TravelTarget } from "./world/useCamera";
import { WorldPlane } from "./world/WorldPlane";
import "./theme/tokens.css";

export default function App() {
  return (
    <AmbientProvider>
      <PhotoBackground />
      <WorldShell />
    </AmbientProvider>
  );
}

const useViewportSize = (): { width: number; height: number } => {
  const [size, setSize] = useState(() => ({
    width: typeof window === "undefined" ? 1_200 : window.innerWidth,
    height: typeof window === "undefined" ? 800 : window.innerHeight,
  }));

  useEffect(() => {
    const update = (): void => setSize({ width: window.innerWidth, height: window.innerHeight });
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  return size;
};

function WorldShell() {
  const connection = useConnection();
  const connected = connection.state === "connectedLocked" || connection.state === "unlocked";
  const { placements, updatePlacement, resetToDefault } = useLayoutBridge(connected);
  const viewport = useViewportSize();
  const [activeDomain, setActiveDomain] = useState<DomainId | null>(null);
  const [announcement, setAnnouncement] = useState("");

  const focusCard = useCallback((domain: DomainId): void => {
    window.requestAnimationFrame(() => {
      const target = document.querySelector<HTMLButtonElement>(`[data-card-slot="${domain}"]`);
      target?.focus();
    });
  }, []);

  const onArrive = useCallback(
    (target: TravelTarget): void => {
      if (target.kind !== "domain") return;
      const domain = target.placement.domain as DomainId;
      setActiveDomain(domain);
      setAnnouncement(`Navigated to ${domainLabel(domain)}`);
      focusCard(domain);
    },
    [focusCard],
  );

  const camera = useCamera({
    viewportWidth: viewport.width,
    viewportHeight: viewport.height,
    onArrive,
  });

  const onOpen = useCallback((domain: DomainId): void => {
    setActiveDomain(domain);
  }, []);

  const travelHome = useCallback(() => {
    setActiveDomain(null);
    camera.home();
  }, [camera]);

  const movePlacement = useCallback(
    (placement: CardPlacement, persist: boolean): void => updatePlacement(placement, persist),
    [updatePlacement],
  );

  if (!connected) return null;

  return (
    <main className="artemis-shell">
      <div className="world-topbar">
        <span className="world-topbar__brand">Artemis</span>
        <span className="world-topbar__crumb">
          Home{activeDomain === null ? "" : ` / ${domainLabel(activeDomain)}`}
        </span>
        <span className="world-topbar__spacer" />
        <span className="world-status">{connection.state === "unlocked" ? "Vault unlocked" : "Vault locked"}</span>
        <button type="button" onClick={travelHome}>
          Home
        </button>
        <button type="button" onClick={resetToDefault}>
          Reset layout
        </button>
      </div>
      <WorldPlane
        placements={placements}
        camera={camera}
        onMovePlacement={movePlacement}
        onOpen={onOpen}
      />
      <Dock placements={placements} activeDomain={activeDomain} travelTo={camera.travelTo} />
      <Minimap placements={placements} cam={camera.cam} bounds={camera.bounds} />
      <div className="sr-only" aria-live="polite">
        {announcement}
      </div>
    </main>
  );
}
