import type { CardPlacement } from "../api/dto";
import type { DomainId } from "../domains";
import { domainLabel } from "../domains";
import type { TravelTarget } from "./useCamera";

export interface DockProps {
  placements: CardPlacement[];
  activeDomain: DomainId | null;
  travelTo: (target: TravelTarget) => void;
}

const domainFrom = (domain: string): DomainId => domain as DomainId;

/** Keyboard-reachable node index for the world map, driven by the brain's actual nodes
 * (capabilities). Empty until a capability is built. */
export function Dock({ placements, activeDomain, travelTo }: DockProps) {
  return (
    <nav className="world-dock glass" aria-label="Domains">
      {placements.map((placement) => {
        const domain = placement.domain;
        const label = domainLabel(domainFrom(domain)) ?? domain;
        return (
          <button
            key={domain}
            type="button"
            className="world-dock__button"
            aria-current={activeDomain === domain ? "page" : undefined}
            onClick={() => travelTo({ kind: "domain", placement })}
          >
            <span className="world-dock__abbr" aria-hidden="true">
              {label.slice(0, 2)}
            </span>
            <span className="world-dock__tip">{label}</span>
          </button>
        );
      })}
    </nav>
  );
}
