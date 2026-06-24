import { describe, expect, it } from "vitest";

import {
  cameraForCenter,
  clampCamera,
  clampRubberband,
  defaultBounds,
  home,
  pan,
  screenToWorld,
  worldToScreen,
  zoomToward,
} from "./camera";

describe("camera math", () => {
  const bounds = defaultBounds(1_200, 800);

  it("pans by screen-space offsets", () => {
    expect(pan({ tx: 10, ty: 20, scale: 1 }, 5, -8)).toEqual({ tx: 15, ty: 12, scale: 1 });
  });

  it("keeps the cursor world point fixed while zooming toward the cursor", () => {
    const cam = { tx: -300, ty: -120, scale: 0.8 };
    const cursor = { x: 420, y: 275 };
    const before = screenToWorld(cam, cursor);
    const next = zoomToward(cam, 1.35, cursor.x, cursor.y);
    const after = screenToWorld(next, cursor);

    expect(after.x).toBeCloseTo(before.x, 8);
    expect(after.y).toBeCloseTo(before.y, 8);
  });

  it("rubber-bands overshoot and hard clamps back inside bounds", () => {
    const overshot = { tx: 900, ty: 720, scale: 1 };
    const rubbered = clampRubberband(overshot, bounds);
    const clamped = clampCamera(overshot, bounds);

    expect(rubbered.tx).toBeLessThan(overshot.tx);
    expect(rubbered.ty).toBeLessThan(overshot.ty);
    expect(rubbered.tx).toBeGreaterThan(clamped.tx);
    expect(rubbered.ty).toBeGreaterThan(clamped.ty);
    expect(clamped.tx).toBeLessThanOrEqual(bounds.margin);
    expect(clamped.ty).toBeLessThanOrEqual(bounds.margin);
  });

  it("round-trips screen and world points", () => {
    const cam = { tx: -500, ty: -350, scale: 1.4 };
    const world = { x: 1_220, y: 840 };
    const screen = worldToScreen(cam, world);
    expect(screenToWorld(cam, screen).x).toBeCloseTo(world.x, 8);
    expect(screenToWorld(cam, screen).y).toBeCloseTo(world.y, 8);
  });

  it("centres the requested point and the home overview", () => {
    const focused = cameraForCenter({ x: 900, y: 700 }, 1, bounds);
    expect(worldToScreen(focused, { x: 900, y: 700 })).toEqual({ x: 600, y: 400 });

    const overview = home(bounds);
    const centered = worldToScreen(overview, { x: 1_300, y: 880 });
    expect(centered.x).toBeCloseTo(600, 8);
    expect(centered.y).toBeCloseTo(400, 8);
  });
});
