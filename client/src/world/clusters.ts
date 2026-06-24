import type { CardPlacement } from "../api/dto";
import type { DomainCluster, DomainId } from "../domains";
import { domainCluster } from "../domains";
import { CORE, WORLD_HEIGHT, WORLD_WIDTH } from "./camera";

export const CARD_WIDTH = 250;
export const CARD_HEIGHT = 150;

export const WORLD_DOMAINS = [
  "email",
  "people",
  "schedule",
  "tasks",
  "projects",
  "travel",
  "memory",
  "knowledge",
  "review",
  "health",
  "finance",
] as const satisfies readonly DomainId[];

const seedCenters = {
  email: { x: CORE.x - 680, y: CORE.y - 290 },
  people: { x: CORE.x - 510, y: CORE.y - 45 },
  schedule: { x: CORE.x - 155, y: CORE.y - 525 },
  tasks: { x: CORE.x + 165, y: CORE.y - 500 },
  projects: { x: CORE.x + 455, y: CORE.y - 340 },
  travel: { x: CORE.x + 680, y: CORE.y - 95 },
  memory: { x: CORE.x - 420, y: CORE.y + 380 },
  knowledge: { x: CORE.x - 60, y: CORE.y + 500 },
  review: { x: CORE.x + 305, y: CORE.y + 390 },
  health: { x: CORE.x + 615, y: CORE.y + 240 },
  finance: { x: CORE.x + 695, y: CORE.y + 485 },
} as const satisfies Record<DomainId, { x: number; y: number }>;

export const clusterPoles = {
  Comms: { x: CORE.x - 610, y: CORE.y - 170 },
  Planning: { x: CORE.x + 290, y: CORE.y - 365 },
  Knowledge: { x: CORE.x - 70, y: CORE.y + 420 },
  Self: { x: CORE.x + 650, y: CORE.y + 360 },
} as const satisfies Record<DomainCluster, { x: number; y: number }>;

const placementFor = (domain: DomainId): CardPlacement => {
  const center = seedCenters[domain];
  return {
    id: domain,
    domain,
    cluster: domainCluster(domain),
    x: center.x - CARD_WIDTH / 2,
    y: center.y - CARD_HEIGHT / 2,
    w: CARD_WIDTH,
    h: CARD_HEIGHT,
  };
};

/** Returns the canonical 11-domain, four-cluster seed map. */
export const defaultPlacements = (): CardPlacement[] => WORLD_DOMAINS.map(placementFor);

export const isWithinWorld = (placement: CardPlacement): boolean =>
  placement.x >= 0 &&
  placement.y >= 0 &&
  placement.x + placement.w <= WORLD_WIDTH &&
  placement.y + placement.h <= WORLD_HEIGHT;

export const placementCenter = (placement: CardPlacement): { x: number; y: number } => ({
  x: placement.x + placement.w / 2,
  y: placement.y + placement.h / 2,
});
