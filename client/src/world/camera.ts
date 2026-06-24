export interface Camera {
  tx: number;
  ty: number;
  scale: number;
}

export interface Point {
  x: number;
  y: number;
}

export interface WorldBounds {
  width: number;
  height: number;
  viewportWidth: number;
  viewportHeight: number;
  minScale: number;
  maxScale: number;
  margin: number;
}

export const WORLD_WIDTH = 2_600;
export const WORLD_HEIGHT = 1_760;
export const CORE = { x: WORLD_WIDTH / 2, y: WORLD_HEIGHT / 2 } as const;
export const HOME_SCALE = 0.72;
export const FOCUS_SCALE = 1.05;

export const easeInOutCubic = (t: number): number =>
  t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;

export const lerp = (from: number, to: number, t: number): number => from + (to - from) * t;

const clamp = (value: number, min: number, max: number): number =>
  Math.max(min, Math.min(max, value));

const rubber = (value: number, min: number, max: number): number => {
  if (value < min) return min - (min - value) * 0.35;
  if (value > max) return max + (value - max) * 0.35;
  return value;
};

export const defaultBounds = (
  viewportWidth: number,
  viewportHeight: number,
): WorldBounds => ({
  width: WORLD_WIDTH,
  height: WORLD_HEIGHT,
  viewportWidth,
  viewportHeight,
  minScale: 0.42,
  maxScale: 2.4,
  margin: 180,
});

/** Converts a world-space point to screen coordinates under transform-origin: 0 0. */
export const worldToScreen = (cam: Camera, point: Point): Point => ({
  x: point.x * cam.scale + cam.tx,
  y: point.y * cam.scale + cam.ty,
});

/** Converts a screen-space point to world coordinates under transform-origin: 0 0. */
export const screenToWorld = (cam: Camera, point: Point): Point => ({
  x: (point.x - cam.tx) / cam.scale,
  y: (point.y - cam.ty) / cam.scale,
});

/** Adds a screen-space pan delta to the current camera. */
export const pan = (cam: Camera, dx: number, dy: number): Camera => ({
  ...cam,
  tx: cam.tx + dx,
  ty: cam.ty + dy,
});

/** Zooms around a screen-space cursor while keeping that cursor's world point fixed. */
export const zoomToward = (cam: Camera, factor: number, px: number, py: number): Camera => {
  const nextScale = cam.scale * factor;
  const worldPoint = screenToWorld(cam, { x: px, y: py });
  return {
    scale: nextScale,
    tx: px - worldPoint.x * nextScale,
    ty: py - worldPoint.y * nextScale,
  };
};

export const cameraForCenter = (center: Point, scale: number, bounds: WorldBounds): Camera => ({
  scale: clamp(scale, bounds.minScale, bounds.maxScale),
  tx: bounds.viewportWidth / 2 - center.x * clamp(scale, bounds.minScale, bounds.maxScale),
  ty: bounds.viewportHeight / 2 - center.y * clamp(scale, bounds.minScale, bounds.maxScale),
});

/** Returns the overview camera centred on the brain core and world bounds. */
export const home = (bounds: WorldBounds): Camera => {
  const scale = Math.min(
    HOME_SCALE,
    (bounds.viewportWidth * 0.82) / bounds.width,
    (bounds.viewportHeight * 0.82) / bounds.height,
  );
  return cameraForCenter(CORE, Math.max(bounds.minScale, scale), bounds);
};

const hardLimits = (cam: Camera, bounds: WorldBounds): { minTx: number; maxTx: number; minTy: number; maxTy: number } => {
  const scaledWidth = bounds.width * cam.scale;
  const scaledHeight = bounds.height * cam.scale;
  const margin = bounds.margin * cam.scale;
  const minTx = bounds.viewportWidth - scaledWidth - margin;
  const maxTx = margin;
  const minTy = bounds.viewportHeight - scaledHeight - margin;
  const maxTy = margin;
  return scaledWidth <= bounds.viewportWidth
    ? {
        minTx: (bounds.viewportWidth - scaledWidth) / 2,
        maxTx: (bounds.viewportWidth - scaledWidth) / 2,
        minTy,
        maxTy,
      }
    : scaledHeight <= bounds.viewportHeight
      ? {
          minTx,
          maxTx,
          minTy: (bounds.viewportHeight - scaledHeight) / 2,
          maxTy: (bounds.viewportHeight - scaledHeight) / 2,
        }
      : { minTx, maxTx, minTy, maxTy };
};

/** Applies the mockup's rubber-band easing for temporary pan overshoot. */
export const clampRubberband = (cam: Camera, bounds: WorldBounds): Camera => {
  const scale = clamp(cam.scale, bounds.minScale, bounds.maxScale);
  const limits = hardLimits({ ...cam, scale }, bounds);
  return {
    scale,
    tx: rubber(cam.tx, limits.minTx, limits.maxTx),
    ty: rubber(cam.ty, limits.minTy, limits.maxTy),
  };
};

/** Removes overshoot and returns a fully in-bounds camera. */
export const clampCamera = (cam: Camera, bounds: WorldBounds): Camera => {
  const scale = clamp(cam.scale, bounds.minScale, bounds.maxScale);
  const limits = hardLimits({ ...cam, scale }, bounds);
  return {
    scale,
    tx: clamp(cam.tx, limits.minTx, limits.maxTx),
    ty: clamp(cam.ty, limits.minTy, limits.maxTy),
  };
};
