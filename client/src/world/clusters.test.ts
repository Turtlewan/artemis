import { describe, expect, it } from "vitest";

import { domainCluster, type DomainCluster, type DomainId } from "../domains";
import { defaultPlacements, isWithinWorld, WORLD_DOMAINS } from "./clusters";

describe("default cluster placements", () => {
  it("seeds all canonical domains, including projects", () => {
    const placements = defaultPlacements();
    expect(placements).toHaveLength(11);
    expect(placements.map((placement) => placement.domain).sort()).toEqual([...WORLD_DOMAINS].sort());
    expect(placements.some((placement) => placement.domain === "projects")).toBe(true);
  });

  it("uses the four named functional clusters from domains.ts", () => {
    const clusters = new Set<DomainCluster>();
    for (const placement of defaultPlacements()) {
      expect(placement.cluster).toBe(domainCluster(placement.domain as DomainId));
      clusters.add(placement.cluster as DomainCluster);
    }
    expect([...clusters].sort()).toEqual(["Comms", "Knowledge", "Planning", "Self"]);
  });

  it("keeps every card inside the world bounds", () => {
    for (const placement of defaultPlacements()) {
      expect(isWithinWorld(placement), placement.domain).toBe(true);
    }
  });
});
