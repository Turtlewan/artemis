import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent as ReactPointerEvent, type WheelEvent } from "react";

import type { CardPlacement } from "../api/dto";
import {
  cameraForCenter,
  clampCamera,
  clampRubberband,
  defaultBounds,
  easeInOutCubic,
  FOCUS_SCALE,
  home as homeCamera,
  lerp,
  pan,
  screenToWorld,
  type Camera,
  type Point,
  type WorldBounds,
  zoomToward,
} from "./camera";
import { placementCenter } from "./clusters";

export type TravelTarget =
  | { kind: "home" }
  | { kind: "domain"; placement: CardPlacement; scale?: number };

export interface UseCameraOptions {
  viewportWidth: number;
  viewportHeight: number;
  onArrive: (target: TravelTarget) => void;
}

export interface CameraController {
  cam: Camera;
  bounds: WorldBounds;
  transform: string;
  isMoving: boolean;
  travelTo: (target: TravelTarget) => void;
  home: () => void;
  onPointerDown: (event: ReactPointerEvent<HTMLElement>) => void;
  onWheel: (event: WheelEvent<HTMLElement>) => void;
  onKeyDown: (event: KeyboardEvent<HTMLElement>) => void;
}

const prefersReducedMotion = (): boolean =>
  typeof window !== "undefined" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const eventPoint = (event: { clientX: number; clientY: number; currentTarget: HTMLElement }): Point => {
  const rect = event.currentTarget.getBoundingClientRect();
  return { x: event.clientX - rect.left, y: event.clientY - rect.top };
};

const targetCamera = (target: TravelTarget, bounds: WorldBounds): Camera => {
  if (target.kind === "home") return homeCamera(bounds);
  return cameraForCenter(placementCenter(target.placement), target.scale ?? FOCUS_SCALE, bounds);
};

/** Owns the world camera store; all animation paths commit `{tx, ty, scale}` through React state. */
export function useCamera({
  viewportWidth,
  viewportHeight,
  onArrive,
}: UseCameraOptions): CameraController {
  const bounds = useMemo(
    () => defaultBounds(Math.max(1, viewportWidth), Math.max(1, viewportHeight)),
    [viewportHeight, viewportWidth],
  );
  const [cam, setCam] = useState<Camera>(() => homeCamera(bounds));
  const [isMoving, setIsMoving] = useState(false);
  const camRef = useRef(cam);
  const boundsRef = useRef(bounds);
  const rafRef = useRef<number | null>(null);
  const panRef = useRef<{ pointerId: number; x: number; y: number; cam: Camera } | null>(null);
  const zoomTargetRef = useRef<number | null>(null);
  const zoomAnchorRef = useRef<{ px: number; py: number; world: Point } | null>(null);

  const commit = useCallback((next: Camera) => {
    camRef.current = next;
    setCam(next);
  }, []);

  const cancelMotion = useCallback(() => {
    if (rafRef.current !== null) {
      window.cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  }, []);

  useEffect(() => {
    camRef.current = cam;
  }, [cam]);

  useEffect(() => {
    boundsRef.current = bounds;
    commit(clampCamera(camRef.current, bounds));
  }, [bounds, commit]);

  const travelTo = useCallback(
    (target: TravelTarget) => {
      cancelMotion();
      const end = clampCamera(targetCamera(target, boundsRef.current), boundsRef.current);
      if (prefersReducedMotion()) {
        setIsMoving(false);
        commit(end);
        onArrive(target);
        return;
      }

      const start = camRef.current;
      const startCenter = screenToWorld(start, {
        x: boundsRef.current.viewportWidth / 2,
        y: boundsRef.current.viewportHeight / 2,
      });
      const endCenter = screenToWorld(end, {
        x: boundsRef.current.viewportWidth / 2,
        y: boundsRef.current.viewportHeight / 2,
      });
      const distance = Math.hypot(endCenter.x - startCenter.x, endCenter.y - startCenter.y);
      const dip = distance > 900 ? 0.32 : distance > 420 ? 0.18 : 0;
      const duration = Math.min(1_150, 640 + distance * 0.26);
      const t0 = performance.now();
      setIsMoving(true);

      const step = (now: number): void => {
        const raw = Math.min(1, (now - t0) / duration);
        const eased = easeInOutCubic(raw);
        const scaleArc = 1 - dip * Math.sin(Math.PI * raw);
        commit({
          tx: lerp(start.tx, end.tx, eased),
          ty: lerp(start.ty, end.ty, eased),
          scale: lerp(start.scale, end.scale, eased) * scaleArc,
        });
        if (raw < 1) {
          rafRef.current = window.requestAnimationFrame(step);
          return;
        }
        rafRef.current = null;
        commit(end);
        setIsMoving(false);
        onArrive(target);
      };

      rafRef.current = window.requestAnimationFrame(step);
    },
    [cancelMotion, commit, onArrive],
  );

  const home = useCallback(() => travelTo({ kind: "home" }), [travelTo]);

  const onPointerDown = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    const target = event.target instanceof HTMLElement ? event.target : null;
    if (event.button !== 0 || target?.closest(".world-card") !== null) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    panRef.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, cam: camRef.current };
    setIsMoving(true);
  }, []);

  useEffect(() => {
    const pointerMove = (event: PointerEvent): void => {
      const active = panRef.current;
      if (active === null || active.pointerId !== event.pointerId) return;
      const next = pan(active.cam, event.clientX - active.x, event.clientY - active.y);
      commit(clampRubberband(next, boundsRef.current));
    };
    const pointerUp = (event: PointerEvent): void => {
      const active = panRef.current;
      if (active === null || active.pointerId !== event.pointerId) return;
      panRef.current = null;
      const settled = clampCamera(camRef.current, boundsRef.current);
      commit(settled);
      setIsMoving(false);
    };
    window.addEventListener("pointermove", pointerMove);
    window.addEventListener("pointerup", pointerUp);
    return () => {
      window.removeEventListener("pointermove", pointerMove);
      window.removeEventListener("pointerup", pointerUp);
    };
  }, [commit]);

  const onWheel = useCallback(
    (event: WheelEvent<HTMLElement>) => {
      event.preventDefault();
      cancelMotion();
      const point = eventPoint(event);
      const currentTarget = zoomTargetRef.current ?? camRef.current.scale;
      const targetScale = Math.max(
        boundsRef.current.minScale,
        Math.min(boundsRef.current.maxScale, currentTarget * Math.exp(-event.deltaY * 0.0011)),
      );
      zoomTargetRef.current = targetScale;
      zoomAnchorRef.current = { px: point.x, py: point.y, world: screenToWorld(camRef.current, point) };
      if (rafRef.current !== null) return;
      setIsMoving(true);

      const step = (): void => {
        const anchor = zoomAnchorRef.current;
        const target = zoomTargetRef.current;
        if (anchor === null || target === null) {
          rafRef.current = null;
          setIsMoving(false);
          return;
        }
        const factor = (camRef.current.scale + (target - camRef.current.scale) * 0.2) / camRef.current.scale;
        const next = clampCamera(zoomToward(camRef.current, factor, anchor.px, anchor.py), boundsRef.current);
        commit(next);
        if (Math.abs(target - next.scale) < 0.0015) {
          zoomTargetRef.current = null;
          zoomAnchorRef.current = null;
          rafRef.current = null;
          setIsMoving(false);
          return;
        }
        rafRef.current = window.requestAnimationFrame(step);
      };
      rafRef.current = window.requestAnimationFrame(step);
    },
    [cancelMotion, commit],
  );

  const onKeyDown = useCallback(
    (event: KeyboardEvent<HTMLElement>) => {
      if (event.key === "Home" || event.key === "Escape") {
        event.preventDefault();
        home();
        return;
      }
      const delta = 72;
      const moves: Record<string, [number, number]> = {
        ArrowUp: [0, delta],
        ArrowDown: [0, -delta],
        ArrowLeft: [delta, 0],
        ArrowRight: [-delta, 0],
      };
      const move = moves[event.key];
      if (move === undefined) return;
      event.preventDefault();
      commit(clampCamera(pan(camRef.current, move[0], move[1]), boundsRef.current));
    },
    [commit, home],
  );

  useEffect(() => () => cancelMotion(), [cancelMotion]);

  return {
    cam,
    bounds,
    transform: `translate(${cam.tx}px, ${cam.ty}px) scale(${cam.scale})`,
    isMoving,
    travelTo,
    home,
    onPointerDown,
    onWheel,
    onKeyDown,
  };
}
