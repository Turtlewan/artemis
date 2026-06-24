import { describe, expect, test } from "vitest";

import { applyCell, allCellKeys, resolveCell, resolveRawCell, timeStateForDate } from "./ambient";
import { cellContrastReport, cellPasses, glassScrimAlpha } from "./contrast";
import { PALETTES } from "./palettes";

const localDate = (iso: string): Date => new Date(iso);

describe("ambient resolver", () => {
  test("maps dates to season and time cells before gating", () => {
    expect(resolveRawCell(localDate("2026-03-21T08:00:00"))).toBe("Spring-morning");
    expect(resolveRawCell(localDate("2026-06-21T13:00:00"))).toBe("Summer-afternoon");
    expect(resolveRawCell(localDate("2026-10-21T19:00:00"))).toBe("Autumn-evening");
    expect(resolveRawCell(localDate("2026-12-21T13:00:00"))).toBe("Winter-afternoon");
  });

  test("honors the 23:30 to 07:15 night boundary", () => {
    expect(timeStateForDate(localDate("2026-01-01T23:29:00"))).toBe("evening");
    expect(timeStateForDate(localDate("2026-01-01T23:30:00"))).toBe("night");
    expect(timeStateForDate(localDate("2026-01-02T00:15:00"))).toBe("night");
    expect(timeStateForDate(localDate("2026-01-02T07:14:00"))).toBe("night");
    expect(timeStateForDate(localDate("2026-01-02T07:15:00"))).toBe("morning");
  });

  test("defines every season and time-state palette", () => {
    expect(allCellKeys()).toHaveLength(16);
    for (const key of allCellKeys()) {
      expect(PALETTES[key]).toBeDefined();
    }
  });

  test("applyCell writes the three ambient CSS variables", () => {
    const values = new Map<string, string>();
    const root = { style: { setProperty: (name: string, value: string) => values.set(name, value) } };
    applyCell("Winter-afternoon", root);
    expect(values.get("--bg")).toBe(PALETTES["Winter-afternoon"].bg);
    expect(values.get("--p")).toBe(PALETTES["Winter-afternoon"].p);
    expect(values.get("--a")).toBe(PALETTES["Winter-afternoon"].a);
  });

  test("resolver never returns draft or failing cells", () => {
    for (const key of allCellKeys()) {
      const [season, time] = key.split("-") as [string, string];
      const month = { Spring: "03", Summer: "06", Autumn: "10", Winter: "12" }[season];
      const hour = { morning: "08:00", afternoon: "13:00", evening: "19:00", night: "23:45" }[
        time
      ];
      const resolved = resolveCell(localDate(`2026-${month}-21T${hour}:00`));
      expect(PALETTES[resolved].vetted, key).toBe(true);
      expect(cellPasses(PALETTES[resolved]), key).toBe(true);
    }
  });
});

describe("contrast gate", () => {
  test("classifies all cells and requires every vetted cell to pass", () => {
    for (const key of allCellKeys()) {
      const cell = PALETTES[key];
      const report = cellContrastReport(cell);
      expect(report.bodyOnBg, `${key} body`).toBeGreaterThanOrEqual(4.5);
      expect(report.largeUiOnBg, `${key} large/ui`).toBeGreaterThanOrEqual(3);
      expect(
        report.primaryAccentContrast >= 3 || report.primaryAccentDelta >= 20,
        `${key} p/a distinction`,
      ).toBe(true);
      if (cell.vetted) {
        expect(cellPasses(cell), `${key} vetted gate`).toBe(true);
      }
    }
  });

  test("glass scrim floor preserves body text contrast for light and dark photo samples", () => {
    expect(glassScrimAlpha()).toBeGreaterThanOrEqual(0.72);
    for (const key of allCellKeys()) {
      const report = cellContrastReport(PALETTES[key]);
      expect(report.bodyOnGlassLight, `${key} light photo`).toBeGreaterThanOrEqual(4.5);
      expect(report.bodyOnGlassDark, `${key} dark photo`).toBeGreaterThanOrEqual(4.5);
    }
  });

  test("focus ring is legible for every vetted cell", () => {
    for (const key of allCellKeys()) {
      if (!PALETTES[key].vetted) continue;
      const report = cellContrastReport(PALETTES[key]);
      expect(report.focusOnBg, `${key} focus bg`).toBeGreaterThanOrEqual(3);
      expect(report.focusOnGlassLight, `${key} focus light glass`).toBeGreaterThanOrEqual(3);
      expect(report.focusOnGlassDark, `${key} focus dark glass`).toBeGreaterThanOrEqual(3);
    }
  });
});
