import { describe, expect, it } from "vitest";

import { firstLastInvert, morphKeyframes } from "./morph";

describe("card morph geometry", () => {
  it("computes the FLIP inverse from card rect to overlay rect", () => {
    expect(
      firstLastInvert(
        { left: 100, top: 80, width: 250, height: 150 },
        { left: 300, top: 200, width: 500, height: 400 },
      ),
    ).toEqual({ tx: -200, ty: -120, scale: 0.5 });
  });

  it("emits transform and opacity keyframes only", () => {
    const frames = morphKeyframes({ tx: -20, ty: 16, scale: 0.4 });
    expect(frames).toHaveLength(2);

    for (const frame of frames) {
      expect(Object.keys(frame).sort()).toEqual(["opacity", "transform"]);
      expect("top" in frame).toBe(false);
      expect("left" in frame).toBe(false);
      expect("width" in frame).toBe(false);
      expect("height" in frame).toBe(false);
    }
  });
});

