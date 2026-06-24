import { useCallback, useEffect, useRef, useState } from "react";

import type { CardPlacement } from "./api/dto";
import { DetailOverlay } from "./card/DetailOverlay";
import { useCardOverlay } from "./card/useCardOverlay";
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
  const overlay = useCardOverlay();
  const pendingOpenRef = useRef<DomainId | null>(null);
  const topbarRef = useRef<HTMLDivElement | null>(null);
  const worldRef = useRef<HTMLDivElement | null>(null);
  const dockRef = useRef<HTMLDivElement | null>(null);
  const minimapRef = useRef<HTMLDivElement | null>(null);
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
      if (pendingOpenRef.current === domain) {
        pendingOpenRef.current = null;
        overlay.open(domain);
        return;
      }
      focusCard(domain);
    },
    [focusCard, overlay],
  );

  const camera = useCamera({
    viewportWidth: viewport.width,
    viewportHeight: viewport.height,
    onArrive,
  });

  const onOpen = useCallback(
    (domain: DomainId): void => {
      const placement = placements.find((candidate) => candidate.domain === domain);
      if (placement === undefined) return;
      overlay.originRef.current = document.querySelector<HTMLElement>(`[data-card-slot="${domain}"]`);
      pendingOpenRef.current = domain;
      camera.travelTo({ kind: "domain", placement });
    },
    [camera, overlay.originRef, placements],
  );

  const travelHome = useCallback(() => {
    setActiveDomain(null);
    overlay.close();
    camera.home();
  }, [camera, overlay]);

  const movePlacement = useCallback(
    (placement: CardPlacement, persist: boolean): void => updatePlacement(placement, persist),
    [updatePlacement],
  );

  const overlayOpen = overlay.openId !== null;

  const setBackgroundInert = useCallback((node: HTMLElement | null, inert: boolean): void => {
    if (node === null) return;
    if (inert) {
      node.setAttribute("inert", "");
      node.setAttribute("aria-hidden", "true");
      return;
    }
    node.removeAttribute("inert");
    node.removeAttribute("aria-hidden");
  }, []);

  useEffect(() => {
    for (const node of [topbarRef.current, worldRef.current, dockRef.current, minimapRef.current]) {
      setBackgroundInert(node, overlayOpen);
    }
  }, [overlayOpen, setBackgroundInert]);

  if (!connected) return null;

  return (
    <main className="artemis-shell">
      <div className="world-topbar" ref={topbarRef} data-testid="world-topbar-layer">
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
      <div ref={worldRef} data-testid="world-plane-layer">
        <WorldPlane
          placements={placements}
          camera={camera}
          onMovePlacement={movePlacement}
          onOpen={onOpen}
        />
      </div>
      <div ref={dockRef} data-testid="world-dock-layer">
        <Dock placements={placements} activeDomain={activeDomain} travelTo={camera.travelTo} />
      </div>
      <div ref={minimapRef} data-testid="world-minimap-layer">
        <Minimap placements={placements} cam={camera.cam} bounds={camera.bounds} />
      </div>
      <div className="sr-only" aria-live="polite">
        {announcement}
      </div>
      <DetailOverlay openId={overlay.openId} onClose={overlay.close} originRef={overlay.originRef} />
    </main>
  );
}
