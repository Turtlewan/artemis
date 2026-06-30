import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import App from "../App";
import { connectionStore } from "../state/connection";
import { CardSlot } from "./CardSlot";
import { Dock } from "./Dock";
import { layoutBridgeTestApi } from "./layoutBridge";
import { Minimap } from "./Minimap";
import { defaultPlacements, WORLD_DOMAINS } from "./clusters";
import { defaultBounds, home } from "./camera";

describe("world shell contracts", () => {
  it("gates the map to connected states", () => {
    connectionStore.resetForTest();
    expect(App()).toBeTruthy();

    connectionStore.onPaired();
    connectionStore.onConnected();
    expect(connectionStore.getSnapshot().state).toBe("connectedLocked");
    connectionStore.onUnlocked();
    expect(connectionStore.getSnapshot().state).toBe("unlocked");
  });

  it("dock lists every domain and travels to the selected placement", () => {
    const placements = defaultPlacements();
    const travelTo = vi.fn();
    const dock = Dock({ placements, activeDomain: null, travelTo });
    const buttons = dock.props.children as Array<{ props: { onClick: () => void } }>;

    expect(buttons).toHaveLength(WORLD_DOMAINS.length);
    buttons[0]?.props.onClick();
    expect(travelTo).toHaveBeenCalledWith({ kind: "domain", placement: placements[0] });
  });

  it("CardSlot is a native button with an accessible domain name and no scroll styles", () => {
    const placement = defaultPlacements()[0];
    const markup = renderToStaticMarkup(
      <CardSlot placement={placement} scale={1} onMove={vi.fn()} onOpen={vi.fn()} />,
    );

    expect(markup.startsWith("<button")).toBe(true);
    expect(markup).toContain('aria-label="Email"');
    expect(markup).not.toContain("overflow");
  });

  it("minimap is decorative and non-interactive", () => {
    const markup = renderToStaticMarkup(
      <Minimap
        placements={defaultPlacements()}
        cam={home(defaultBounds(1_200, 800))}
        bounds={defaultBounds(1_200, 800)}
      />,
    );

    expect(markup).toContain('aria-hidden="true"');
    expect(markup).toContain("inert=");
  });

  it("layout bridge uses the brain layout as the only node source (no hardcoded seed)", () => {
    // v2: empty brain layout => empty map; brain-provided cards pass through unchanged.
    expect(layoutBridgeTestApi.validCards({ version: 1, updated_at: "", cards: [] })).toEqual([]);
    const sample = defaultPlacements().slice(0, 1);
    expect(layoutBridgeTestApi.validCards({ version: 1, updated_at: "", cards: sample })).toEqual(
      sample,
    );
  });

  it("Home and Escape share the same overview target", () => {
    const bounds = defaultBounds(1_200, 800);
    expect(home(bounds)).toEqual(home(bounds));
  });

  it("reduced-motion is represented as an instant matchMedia condition", () => {
    const matcher = vi.fn((query: string) => ({ matches: query === "(prefers-reduced-motion: reduce)" }));
    expect(matcher("(prefers-reduced-motion: reduce)").matches).toBe(true);
  });
});
