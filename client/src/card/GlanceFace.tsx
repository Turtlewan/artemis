import type { DomainId } from "../domains";
import { domainLabel } from "../domains";
import { getDomainGlance } from "./registry";
import type { GlanceContent } from "./types";

const styles = `
.card-glance{display:flex;width:100%;height:100%;overflow:hidden}
.card-glance--count{align-items:center;justify-content:flex-start}
.card-glance__count{display:flex;align-items:baseline;gap:9px;min-width:0}
.card-glance__value{font-size:30px;line-height:1;font-weight:700;color:var(--text)}
.card-glance__label{min-width:0;font-size:12px;line-height:1.2;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.card-glance--tiles{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.card-glance__tile{display:flex;min-width:0;min-height:0;flex-direction:column;justify-content:center;border:1px solid var(--hair);border-radius:8px;padding:8px;background:color-mix(in srgb,var(--p) 9%,transparent);overflow:hidden}
.card-glance__tile-value{font-size:17px;line-height:1.1;font-weight:700;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.card-glance__tile-label{font-size:10px;line-height:1.2;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
`;

let stylesMounted = false;

const ensureStyles = (): void => {
  if (stylesMounted || typeof document === "undefined") return;
  const style = document.createElement("style");
  style.dataset.cardGlance = "true";
  style.textContent = styles;
  document.head.append(style);
  stylesMounted = true;
};

/** Fixed glance face variants for world cards; these surfaces never content-scroll. */
export function GlanceFace({ content }: { content: GlanceContent }) {
  ensureStyles();

  if (content.kind === "count") {
    return (
      <span className="card-glance card-glance--count" data-card-glance>
        <span className="card-glance__count">
          <span className="card-glance__value">{content.value}</span>
          <span className="card-glance__label">{content.label}</span>
        </span>
      </span>
    );
  }

  return (
    <span className="card-glance card-glance--tiles" data-card-glance>
      {content.tiles.map((tile) => (
        <span className="card-glance__tile" key={`${tile.label}:${tile.value}`}>
          <span className="card-glance__tile-value">{tile.value}</span>
          <span className="card-glance__tile-label">{tile.label}</span>
        </span>
      ))}
    </span>
  );
}

/** Registry-backed glance host with a placeholder count face until CLIENT-screens registers content. */
export function GlanceHost({ domainId }: { domainId: DomainId }) {
  const RegisteredGlance = getDomainGlance(domainId);
  if (RegisteredGlance !== undefined) return <RegisteredGlance domainId={domainId} />;
  return <GlanceFace content={{ kind: "count", value: "—", label: domainLabel(domainId) }} />;
}
