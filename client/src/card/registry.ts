import type { DomainId } from "../domains";
import type { DomainDetailComponent, DomainGlanceComponent } from "./types";

const detailRegistry = new Map<DomainId, DomainDetailComponent>();
const glanceRegistry = new Map<DomainId, DomainGlanceComponent>();

export interface DomainRegistration {
  glance?: DomainGlanceComponent;
  detail?: DomainDetailComponent;
}

/** Registers optional glance and detail components for a domain. CLIENT-screens owns the calls. */
export const registerDomain = (id: DomainId, registration: DomainRegistration): void => {
  if (registration.detail !== undefined) detailRegistry.set(id, registration.detail);
  if (registration.glance !== undefined) glanceRegistry.set(id, registration.glance);
};

export const getDomainDetail = (id: DomainId): DomainDetailComponent | undefined => detailRegistry.get(id);

export const getDomainGlance = (id: DomainId): DomainGlanceComponent | undefined => glanceRegistry.get(id);

