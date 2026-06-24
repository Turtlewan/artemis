import type { ComponentType } from "react";

import type { DomainId } from "../domains";

/** Props supplied to per-domain detail panels registered by CLIENT-screens. */
export interface DomainDetailProps {
  domainId: DomainId;
  onClose: () => void;
}

/** Props supplied to per-domain glance faces registered by CLIENT-screens. */
export interface DomainGlanceProps {
  domainId: DomainId;
}

/** Compact, non-scrolling glance content shown inside a world CardSlot. */
export type GlanceContent =
  | { kind: "count"; value: string | number; label: string }
  | { kind: "tiles"; tiles: { value: string; label: string }[] };

export type DomainDetailComponent = ComponentType<DomainDetailProps>;
export type DomainGlanceComponent = ComponentType<DomainGlanceProps>;

