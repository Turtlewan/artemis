import type { CardPlacement } from "../api/dto";
import type { Camera, WorldBounds } from "./camera";

export interface MinimapProps {
  placements: CardPlacement[];
  cam: Camera;
  bounds: WorldBounds;
}

const MINI_WIDTH = 132;
const MINI_HEIGHT = 90;

/** Decorative map overview; pointer and keyboard navigation are intentionally owned by the dock. */
export function Minimap({ placements, cam, bounds }: MinimapProps) {
  const sx = MINI_WIDTH / bounds.width;
  const sy = MINI_HEIGHT / bounds.height;
  const viewport = {
    x: Math.max(0, (-cam.tx / cam.scale) * sx),
    y: Math.max(0, (-cam.ty / cam.scale) * sy),
    w: Math.min(MINI_WIDTH, (bounds.viewportWidth / cam.scale) * sx),
    h: Math.min(MINI_HEIGHT, (bounds.viewportHeight / cam.scale) * sy),
  };
  return (
    <div className="world-minimap glass" aria-hidden="true" inert>
      {placements.map((placement) => (
        <span
          key={placement.id}
          className="world-minimap__dot"
          style={{
            left: `${(placement.x + placement.w / 2) * sx}px`,
            top: `${(placement.y + placement.h / 2) * sy}px`,
          }}
        />
      ))}
      <span
        className="world-minimap__viewport"
        style={{
          left: `${viewport.x}px`,
          top: `${viewport.y}px`,
          width: `${viewport.w}px`,
          height: `${viewport.h}px`,
        }}
      />
    </div>
  );
}
