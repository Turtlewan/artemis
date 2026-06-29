import { useEffect, useMemo, useRef } from "react";

import type { DomainId } from "../domains";
import { DOMAIN_RELATIONSHIPS, SPOKE_DOMAINS } from "./relationships";

type Point = { x: number; y: number };

export type NeuralWebLayout = Record<DomainId, Point>;

export type NeuralWebProps = {
  layout: NeuralWebLayout;
  core: Point;
  width: number;
  height: number;
  transform?: string;
};

type Curve = {
  key: string;
  kind: "edge" | "spoke";
  d: string;
};

const WHITE_COMET = "rgba(255,255,255,.95)";
const GOLD_COMET = "rgba(255,201,94,.97)";

const curvePath = (from: Point, to: Point, bend: number): string => {
  const midX = (from.x + to.x) / 2;
  const midY = (from.y + to.y) / 2;
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const length = Math.hypot(dx, dy) || 1;
  const nx = -dy / length;
  const ny = dx / length;
  const offset = length * bend;
  return `M${from.x},${from.y} Q${midX + nx * offset},${midY + ny * offset} ${to.x},${to.y}`;
};

const prefersReducedMotion = (): boolean =>
  typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Decorative-only neural web; actual events surface elsewhere, so reduced motion loses no information. */
export function NeuralWeb({ layout, core, width, height, transform }: NeuralWebProps) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const overlayRef = useRef<SVGGElement | null>(null);
  const curves = useMemo<Curve[]>(() => {
    // A domain only contributes a spoke/edge once it has a placement on the
    // map; layout is keyed by placed domains, so skip endpoints not yet present
    // (e.g. empty/partial placements right after connect) to avoid drawing from
    // an undefined point.
    const spokes = SPOKE_DOMAINS.flatMap<Curve>((id, index) => {
      const point = layout[id];
      if (point === undefined) return [];
      return [
        {
          key: `spoke:${id}`,
          kind: "spoke",
          d: curvePath(core, point, (index % 2 === 0 ? -1 : 1) * 0.1),
        },
      ];
    });
    const edges = DOMAIN_RELATIONSHIPS.flatMap<Curve>(([a, b], index) => {
      const from = layout[a];
      const to = layout[b];
      if (from === undefined || to === undefined) return [];
      return [
        {
          key: `edge:${a}-${b}`,
          kind: "edge",
          d: curvePath(from, to, (index % 2 === 0 ? -1 : 1) * 0.16),
        },
      ];
    });
    return [...spokes, ...edges];
  }, [core, layout]);

  useEffect(() => {
    if (prefersReducedMotion()) return;

    const svg = svgRef.current;
    const overlay = overlayRef.current;
    if (svg === null || overlay === null) return;

    const namespace = "http://www.w3.org/2000/svg";
    const fire = (curve: Curve, gold: boolean): void => {
      const path = document.createElementNS(namespace, "path");
      path.setAttribute("d", curve.d);
      path.setAttribute("class", gold ? "neural-web__comet neural-web__comet--gold" : "neural-web__comet");
      path.style.stroke = gold ? GOLD_COMET : WHITE_COMET;
      path.style.clipPath = "inset(0 100% 0 0)";
      overlay.append(path);
      const motion = path.animate(
        [
          // No translateX: the clip-path reveal makes the comet travel ALONG the
          // line; a horizontal translate would drift it off the static curve.
          { opacity: 0, clipPath: "inset(0 100% 0 0)" },
          { opacity: 1, offset: 0.14, clipPath: "inset(0 52% 0 0)" },
          { opacity: 1, offset: 0.84, clipPath: "inset(0 0 0 52%)" },
          { opacity: 0, clipPath: "inset(0 0 0 100%)" },
        ],
        { duration: gold ? 1_700 : 3_000, easing: "linear" },
      );
      motion.onfinish = () => path.remove();
    };

    const edgeCurves = curves.filter((curve) => curve.kind === "edge");
    const spokeCurves = curves.filter((curve) => curve.kind === "spoke");
    let edgeIndex = 0;
    let spokeIndex = 0;
    const whiteTimer = window.setInterval(() => {
      if (edgeCurves.length > 0) fire(edgeCurves[edgeIndex++ % edgeCurves.length], false);
    }, 3_000);
    const goldTimer = window.setInterval(() => {
      if (spokeCurves.length > 0) fire(spokeCurves[spokeIndex++ % spokeCurves.length], true);
    }, 1_700);

    return () => {
      window.clearInterval(whiteTimer);
      window.clearInterval(goldTimer);
      overlay.replaceChildren();
    };
  }, [curves]);

  return (
    <svg
      ref={svgRef}
      className="neural-web"
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      style={{ transform, transformOrigin: "0 0" }}
      pointerEvents="none"
      aria-hidden="true"
    >
      <g>
        {curves.map((curve) => (
          <path
            key={`${curve.key}:base`}
            className={curve.kind === "spoke" ? "neural-web__curve neural-web__curve--spoke" : "neural-web__curve"}
            d={curve.d}
          />
        ))}
        {prefersReducedMotion()
          ? null
          : curves.map((curve) => (
              <path key={`${curve.key}:flow`} className="neural-web__flow" d={curve.d} />
            ))}
      </g>
      <g ref={overlayRef} />
    </svg>
  );
}
