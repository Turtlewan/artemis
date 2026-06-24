export interface MorphInvert {
  tx: number;
  ty: number;
  scale: number;
}

export type MorphKeyframe = {
  transform: string;
  opacity: number;
};

type RectLike = Pick<DOMRectReadOnly, "left" | "top" | "width" | "height">;

/** Computes the FLIP inverse from the origin card rect to the final overlay rect. */
export const firstLastInvert = (fromRect: RectLike, toRect: RectLike): MorphInvert => ({
  tx: fromRect.left - toRect.left,
  ty: fromRect.top - toRect.top,
  scale: fromRect.width / Math.max(1, toRect.width),
});

/** Transform/opacity-only WAAPI keyframes. Callers read both rects before any DOM write. */
export const morphKeyframes = (invert: MorphInvert): MorphKeyframe[] => [
  {
    transform: `translate(${invert.tx}px, ${invert.ty}px) scale(${invert.scale})`,
    opacity: 0,
  },
  {
    transform: "translate(0px, 0px) scale(1)",
    opacity: 1,
  },
];

