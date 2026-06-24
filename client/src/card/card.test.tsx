import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { CardSlot } from "../world/CardSlot";
import { defaultPlacements } from "../world/clusters";
import { DetailOverlay } from "./DetailOverlay";
import { GlanceFace, GlanceHost } from "./GlanceFace";
import { getDomainDetail, getDomainGlance, registerDomain } from "./registry";

const originRef = { current: null };

describe("card registry", () => {
  it("registers detail and glance components independently", () => {
    const Detail = () => <section>Registered detail</section>;
    const Glance = () => <span>Registered glance</span>;

    registerDomain("email", { detail: Detail, glance: Glance });

    expect(getDomainDetail("email")).toBe(Detail);
    expect(getDomainGlance("email")).toBe(Glance);
    expect(getDomainDetail("people")).toBeUndefined();
  });
});

describe("glance faces", () => {
  it("renders count and tiles faces without scrollable styles", () => {
    const countMarkup = renderToStaticMarkup(
      <GlanceFace content={{ kind: "count", value: 12, label: "needs review" }} />,
    );
    const tilesMarkup = renderToStaticMarkup(
      <GlanceFace
        content={{
          kind: "tiles",
          tiles: [
            { value: "3", label: "today" },
            { value: "9", label: "later" },
          ],
        }}
      />,
    );

    expect(countMarkup).toContain("12");
    expect(countMarkup).toContain("needs review");
    expect(tilesMarkup).toContain("today");
    expect(tilesMarkup).toContain("later");
    expect(`${countMarkup}${tilesMarkup}`).not.toMatch(/overflow:\s*(auto|scroll)/);
  });

  it("keeps the CardSlot accessible name as the domain label in placeholder phase", () => {
    const placement = defaultPlacements().find((candidate) => candidate.domain === "tasks");
    if (placement === undefined) throw new Error("missing tasks placement");

    const markup = renderToStaticMarkup(
      <CardSlot placement={placement} scale={1} onMove={vi.fn()} onOpen={vi.fn()}>
        <GlanceHost domainId="tasks" />
      </CardSlot>,
    );

    expect(markup).toContain('aria-label="Tasks"');
    expect(markup).toContain("—");
    expect(markup).not.toMatch(/overflow:\s*(auto|scroll)/);
  });
});

describe("detail overlay shell", () => {
  it("renders an aria-modal dialog named by the domain title", () => {
    const markup = renderToStaticMarkup(
      <DetailOverlay openId="schedule" onClose={vi.fn()} originRef={originRef} />,
    );

    expect(markup).toContain('role="dialog"');
    expect(markup).toContain('aria-modal="true"');
    expect(markup).toContain('aria-labelledby="card-overlay-title"');
    expect(markup).toContain('id="card-overlay-title"');
    expect(markup).toContain("Schedule");
    expect(markup).toContain('tabindex="-1"');
    expect(markup).toContain('aria-label="Close"');
  });

  it("shows a non-empty fallback heading for unregistered domains", () => {
    const markup = renderToStaticMarkup(
      <DetailOverlay openId="finance" onClose={vi.fn()} originRef={originRef} />,
    );

    expect(markup).toContain("Finance");
    expect(markup).toContain("Finance detail coming");
  });

  it("renders registered fake DomainDetail content", () => {
    const FakeDetail = () => <section data-fake-detail="true">Fake people detail</section>;
    registerDomain("people", { detail: FakeDetail });

    const markup = renderToStaticMarkup(
      <DetailOverlay openId="people" onClose={vi.fn()} originRef={originRef} />,
    );

    expect(markup).toContain('data-fake-detail="true"');
    expect(markup).toContain("Fake people detail");
  });

  it("keeps reduced-motion behavior out of spatial keyframe generation in static render", () => {
    const markup = renderToStaticMarkup(
      <DetailOverlay openId="health" onClose={vi.fn()} originRef={originRef} />,
    );

    expect(markup).not.toContain("translate(");
    expect(markup).not.toContain("scale(");
    expect(markup).not.toContain(["mix", "blend", "mode"].join("-"));
    expect(markup).not.toContain(["content", "visibility"].join("-"));
  });
});
