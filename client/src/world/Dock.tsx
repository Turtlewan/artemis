import type { CardPlacement } from "../api/dto";
import type { DomainId } from "../domains";
import { domainLabel } from "../domains";
import type { TravelTarget } from "./useCamera";
import { WORLD_DOMAINS } from "./clusters";

export interface DockProps {
  placements: CardPlacement[];
  activeDomain: DomainId | null;
  travelTo: (target: TravelTarget) => void;
}

const domainFrom = (domain: string): DomainId => domain as DomainId;

/** Complete keyboard-reachable domain index; this is the world map's navigation path. */
export function Dock({ placements, activeDomain, travelTo }: DockProps) {
  const byDomain = new Map(placements.map((placement) => [placement.domain, placement]));
  return (
    <nav className="world-dock glass" aria-label="Domains">
      {WORLD_DOMAINS.map((domain) => {
        const placement = byDomain.get(domain);
        return (
          <button
            key={domain}
            type="button"
            className="world-dock__button"
            aria-current={activeDomain === domain ? "page" : undefined}
            onClick={() => {
              if (placement !== undefined) travelTo({ kind: "domain", placement });
            }}
          >
            <span className="world-dock__abbr" aria-hidden="true">
              {domainLabel(domainFrom(domain)).slice(0, 2)}
            </span>
            <span className="world-dock__tip">{domainLabel(domainFrom(domain))}</span>
          </button>
        );
      })}
    </nav>
  );
}
