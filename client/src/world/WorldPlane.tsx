import { useEffect, useMemo, useState } from "react";

import type { CardPlacement } from "../api/dto";
import { GlanceHost } from "../card/GlanceFace";
import type { DomainId } from "../domains";
import { NeuralWeb } from "../theme/NeuralWeb";
import { CORE, WORLD_HEIGHT, WORLD_WIDTH } from "./camera";
import { CardSlot } from "./CardSlot";
import { placementCenter } from "./clusters";
import type { CameraController } from "./useCamera";

export interface WorldPlaneProps {
  placements: CardPlacement[];
  camera: CameraController;
  onMovePlacement: (placement: CardPlacement, persist: boolean) => void;
  onOpen: (domain: DomainId) => void;
}

const layoutForWeb = (placements: CardPlacement[]) =>
  Object.fromEntries(placements.map((placement) => [placement.domain, placementCenter(placement)])) as Record<
    DomainId,
    { x: number; y: number }
  >;

const worldStyles = `
.artemis-shell{position:fixed;inset:0;z-index:1;overflow:hidden;color:var(--text);font-family:Inter,system-ui,sans-serif;background:transparent}
.world-stage{position:absolute;inset:0;overflow:hidden;touch-action:none;outline:none;cursor:grab}
.world-stage:active{cursor:grabbing}
.world-plane{position:absolute;left:0;top:0;transform-origin:0 0}
.world-core{position:absolute;left:${CORE.x}px;top:${CORE.y}px;width:190px;height:190px;display:grid;place-items:center;transform:translate(-50%,-50%);pointer-events:none}
.world-core__orb{position:absolute;width:144px;height:144px;border-radius:50%;background:radial-gradient(circle at 50% 42%,color-mix(in srgb,var(--p) 34%,transparent),transparent 68%);filter:blur(2px);animation:world-core-pulse 3.4s ease-in-out infinite}
.world-core__ring{position:absolute;width:136px;height:136px;border-radius:50%;border:1px solid color-mix(in srgb,var(--p) 32%,transparent);animation:world-core-ring 3.4s ease-out infinite}
.world-core__ring:nth-child(3){animation-delay:1.7s}
.world-core__mark{position:relative;width:72px;height:72px;border-radius:50%;border:1px solid color-mix(in srgb,var(--p) 62%,transparent);box-shadow:0 0 18px -4px var(--p),inset 0 0 18px -8px var(--p)}
.world-card{position:absolute;display:flex;flex-direction:column;padding:0;color:var(--text);text-align:left;border-radius:16px;overflow:hidden;cursor:pointer}
.world-card,.world-dock__button{font:inherit}
.world-card__chrome{display:flex;align-items:center;gap:10px;min-height:42px;padding:10px 12px;border-bottom:1px solid var(--hair)}
.world-card__title{font-weight:600;letter-spacing:.01em}
.world-card__grip{margin-left:auto;display:grid;grid-template-columns:repeat(2,4px);gap:3px;width:26px;height:26px;place-content:center;border-radius:7px;color:var(--muted);cursor:grab;touch-action:none}
.world-card__grip:hover,.world-card__grip:focus-visible{background:rgb(255 255 255 / 8%);color:var(--text)}
.world-card__grip span{width:4px;height:4px;border-radius:50%;background:currentColor}
.world-card__body{display:flex;flex:1;align-items:center;justify-content:center;overflow:hidden;padding:12px}
.world-card__placeholder{font-size:13px;color:var(--muted)}
.world-card__move-state{position:absolute;right:10px;bottom:8px;border:1px solid var(--hair);border-radius:8px;padding:3px 7px;background:color-mix(in srgb,var(--p) 16%,transparent);font-size:11px}
.world-card--moving{border-color:color-mix(in srgb,var(--p) 52%,transparent)}
.world-dock{position:absolute;left:50%;bottom:14px;z-index:4;display:flex;gap:6px;padding:7px 10px;border-radius:14px;transform:translateX(-50%)}
.world-dock__button{position:relative;width:36px;height:36px;border:1px solid var(--hair);border-radius:9px;background:color-mix(in srgb,var(--p) 9%,transparent);color:var(--text);cursor:pointer}
.world-dock__button:hover{background:color-mix(in srgb,var(--p) 18%,transparent)}
.world-dock__button[aria-current=page]{border-color:color-mix(in srgb,var(--a) 60%,transparent)}
.world-dock__abbr{font-size:11px;font-weight:700;color:var(--p)}
.world-dock__tip{position:absolute;left:50%;bottom:44px;transform:translateX(-50%);padding:3px 8px;border:1px solid var(--hair);border-radius:7px;background:rgb(8 14 22 / 86%);font-size:10px;white-space:nowrap;opacity:0;pointer-events:none}
.world-dock__button:hover .world-dock__tip,.world-dock__button:focus-visible .world-dock__tip{opacity:1}
.world-minimap{position:absolute;left:16px;bottom:14px;z-index:3;width:132px;height:90px;border-radius:11px;pointer-events:none}
.world-minimap__dot{position:absolute;width:6px;height:6px;border-radius:50%;background:var(--p);box-shadow:0 0 6px var(--p);transform:translate(-50%,-50%)}
.world-minimap__viewport{position:absolute;border:1px solid color-mix(in srgb,var(--p) 58%,transparent);background:color-mix(in srgb,var(--p) 8%,transparent)}
.world-topbar{position:absolute;left:16px;right:16px;top:12px;z-index:5;display:flex;align-items:center;gap:12px;pointer-events:none}
.world-topbar__brand{font-weight:700;letter-spacing:.18em;font-size:12px;text-transform:uppercase}
.world-topbar__crumb{padding-left:12px;border-left:1px solid var(--hair);color:var(--muted);font-size:12px}
.world-topbar__spacer{flex:1}
.world-topbar button{pointer-events:auto;border:1px solid var(--hair);border-radius:9px;background:color-mix(in srgb,var(--p) 12%,transparent);color:var(--text);padding:7px 11px;cursor:pointer}
.world-status{font-size:12px;color:var(--muted)}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@keyframes world-core-pulse{50%{transform:scale(1.08);opacity:.72}}
@keyframes world-core-ring{to{transform:scale(1.42);opacity:0}}
`;

/** The single transformed, overflow-hidden world plane. */
export function WorldPlane({ placements, camera, onMovePlacement, onOpen }: WorldPlaneProps) {
  const [willChange, setWillChange] = useState<"transform" | "auto">("auto");
  const webLayout = useMemo(() => layoutForWeb(placements), [placements]);

  useEffect(() => {
    if (camera.isMoving) {
      setWillChange("transform");
      return;
    }
    const raf = window.requestAnimationFrame(() => setWillChange("auto"));
    return () => window.cancelAnimationFrame(raf);
  }, [camera.isMoving]);

  return (
    <>
      <style>{worldStyles}</style>
      <div
        className="world-stage"
        data-testid="world-stage"
        tabIndex={0}
        onPointerDown={camera.onPointerDown}
        onWheel={camera.onWheel}
        onKeyDown={camera.onKeyDown}
      >
        <NeuralWeb
          layout={webLayout}
          core={CORE}
          width={WORLD_WIDTH}
          height={WORLD_HEIGHT}
          transform={camera.transform}
        />
        <div
          className="world-plane"
          data-testid="world-plane"
          style={{
            width: `${WORLD_WIDTH}px`,
            height: `${WORLD_HEIGHT}px`,
            transform: camera.transform,
            willChange,
          }}
        >
          <div className="world-core" aria-hidden="true">
            <span className="world-core__orb" />
            <span className="world-core__ring" />
            <span className="world-core__ring" />
            <span className="world-core__mark" />
          </div>
          {placements.map((placement) => (
            <CardSlot
              key={placement.id}
              placement={placement}
              scale={camera.cam.scale}
              onMove={onMovePlacement}
              onOpen={onOpen}
            >
              <GlanceHost domainId={placement.domain as DomainId} />
            </CardSlot>
          ))}
        </div>
      </div>
    </>
  );
}
