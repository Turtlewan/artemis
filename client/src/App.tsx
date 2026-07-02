import { useCallback, useEffect, useRef, useState } from "react";

import { askVoice } from "./api/gateway";
import type { CardPlacement } from "./api/dto";
import { AskPopup } from "./ask/AskPopup";
import { askStore } from "./ask/askStore";
import { useAskHotkey } from "./ask/useAskHotkey";
import { PairingScreen } from "./auth/PairingScreen";
import { DetailOverlay } from "./card/DetailOverlay";
import { useCardOverlay } from "./card/useCardOverlay";
import type { DomainId } from "./domains";
import { domainLabel } from "./domains";
import { KeysPanel } from "./settings/KeysPanel";
import { closeKeys, openKeys, useKeysStore } from "./settings/keysStore";
import { useConnection } from "./state/connection";
import { AmbientProvider } from "./theme/AmbientProvider";
import { PhotoBackground } from "./theme/PhotoBackground";
import { Dock } from "./world/Dock";
import { useLayoutBridge } from "./world/layoutBridge";
import { Minimap } from "./world/Minimap";
import { useCamera, type TravelTarget } from "./world/useCamera";
import { WorldPlane } from "./world/WorldPlane";
import "./screens/registry";
import "./theme/tokens.css";

/** Root Artemis application component — wraps the spatial shell in ambient theme providers. */
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
  const ask = useAskHotkey();
  const keys = useKeysStore((current) => current);

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

  const onVoiceTrigger = useCallback(async ({ speak }: { speak: boolean }): Promise<void> => {
    askStore.setSpeaking(speak);
    try {
      for await (const _event of askVoice(speak)) {
        // The popup renders from askStore; the voice stream uses the same SSE event shape.
      }
    } finally {
      askStore.setSpeaking(false);
    }
  }, []);

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

  if (!connected) return <PairingScreen state={connection.state} />;

  return (
    <main className="artemis-shell">
      <div className="world-topbar" ref={topbarRef} data-testid="world-topbar-layer">
        <span className="world-topbar__brand">Artemis</span>
        <span className="world-topbar__crumb">
          Home{activeDomain === null ? "" : ` / ${domainLabel(activeDomain)}`}
        </span>
        <span className="world-topbar__spacer" />
        <span className="world-status">{connection.state === "unlocked" ? "Vault unlocked" : "Vault locked"}</span>
        <button {...ask.askButtonProps}>Ask</button>
        <button type="button" onClick={travelHome}>
          Home
        </button>
        <button type="button" onClick={resetToDefault}>
          Reset layout
        </button>
      </div>
      <AskPopup isOpen={ask.isOpen} onClose={ask.close} onVoiceTrigger={onVoiceTrigger} />
      <div ref={worldRef} data-testid="world-plane-layer">
        <WorldPlane
          placements={placements}
          camera={camera}
          onMovePlacement={movePlacement}
          onOpen={onOpen}
        />
      </div>
      {placements.length === 0 && (
        <div
          data-testid="world-empty"
          role="status"
          style={{
            position: "fixed",
            inset: 0,
            display: "grid",
            placeItems: "center",
            pointerEvents: "none",
            zIndex: 2,
            textAlign: "center",
            padding: "24px",
          }}
        >
          <div style={{ maxWidth: 420, pointerEvents: "auto" }}>
            <p style={{ fontSize: "18px", fontWeight: 600, margin: "0 0 8px" }}>Your map is empty</p>
            <p style={{ fontSize: "14px", opacity: 0.72, margin: "0 0 18px", lineHeight: 1.5 }}>
              No capabilities built yet. Tell Artemis what to build — each new capability appears
              here as a node on the map.
            </p>
            <button
              type="button"
              onClick={ask.open}
              style={{
                padding: "11px 22px",
                borderRadius: "11px",
                border: 0,
                background: "#7aa2ff",
                color: "#0b0c0f",
                fontWeight: 700,
                fontSize: "14px",
                cursor: "pointer",
              }}
            >
              Open Ask
            </button>
          </div>
        </div>
      )}
      <div ref={dockRef} data-testid="world-dock-layer">
        <Dock placements={placements} activeDomain={activeDomain} travelTo={camera.travelTo} />
      </div>
      <div ref={minimapRef} data-testid="world-minimap-layer">
        <Minimap placements={placements} cam={camera.cam} bounds={camera.bounds} />
      </div>
      <div
        data-testid="keys-overlay-layer"
        style={{ position: "fixed", top: 74, right: 18, zIndex: 11 }}
      >
        <button
          type="button"
          aria-label="Open keys panel"
          onClick={() => openKeys()}
          style={{
            width: 40,
            height: 40,
            borderRadius: 8,
            border: "1px solid rgba(255, 255, 255, 0.24)",
            background: "rgba(12, 14, 20, 0.82)",
            color: "#f4f7fb",
            cursor: "pointer",
            fontSize: 18,
          }}
        >
          ⚙
        </button>
      </div>
      <KeysPanel open={keys.open} onClose={closeKeys} pendingKey={keys.pendingKey} />
      <div className="sr-only" aria-live="polite">
        {announcement}
      </div>
      <DetailOverlay openId={overlay.openId} onClose={overlay.close} originRef={overlay.originRef} />
    </main>
  );
}
