import type { PaletteCell } from "./palettes";

const TEXT = "rgb(238 247 255)";
const LARGE_UI = "rgb(168 188 203)";
const FOCUS_RING = "rgb(255 255 255)";
const GLASS_SCRIM_ALPHA = 0.72;

type Rgb = { r: number; g: number; b: number };

const clamp01 = (value: number): number => Math.min(1, Math.max(0, value));

const parseColor = (color: string): Rgb => {
  const hex = /^#(?<r>[0-9a-f]{2})(?<g>[0-9a-f]{2})(?<b>[0-9a-f]{2})$/iu.exec(color);
  if (hex?.groups) {
    return {
      r: Number.parseInt(hex.groups.r, 16),
      g: Number.parseInt(hex.groups.g, 16),
      b: Number.parseInt(hex.groups.b, 16),
    };
  }

  const rgb = /^rgb\(\s*(?<r>\d+)\s+(?<g>\d+)\s+(?<b>\d+)\s*\)$/u.exec(color);
  if (rgb?.groups) {
    return {
      r: Number.parseInt(rgb.groups.r, 10),
      g: Number.parseInt(rgb.groups.g, 10),
      b: Number.parseInt(rgb.groups.b, 10),
    };
  }

  throw new Error(`Unsupported color format: ${color}`);
};

const srgbToLinear = (value: number): number => {
  const channel = value / 255;
  return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
};

/** WCAG 2 relative luminance. */
export const relativeLuminance = (color: string): number => {
  const { r, g, b } = parseColor(color);
  return 0.2126 * srgbToLinear(r) + 0.7152 * srgbToLinear(g) + 0.0722 * srgbToLinear(b);
};

/** WCAG contrast ratio, always >= 1. */
export const contrastRatio = (a: string, b: string): number => {
  const l1 = relativeLuminance(a);
  const l2 = relativeLuminance(b);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
};

const rgbToLab = (color: string): { l: number; a: number; b: number } => {
  const rgb = parseColor(color);
  const pivot = (value: number): number =>
    value > 0.008856 ? Math.cbrt(value) : 7.787 * value + 16 / 116;
  const r = srgbToLinear(rgb.r);
  const g = srgbToLinear(rgb.g);
  const b = srgbToLinear(rgb.b);
  const x = pivot((r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047);
  const y = pivot((r * 0.2126 + g * 0.7152 + b * 0.0722) / 1);
  const z = pivot((r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883);
  return { l: 116 * y - 16, a: 500 * (x - y), b: 200 * (y - z) };
};

/** CIELab Delta E 1976 distance. */
export const deltaE76 = (a: string, b: string): number => {
  const left = rgbToLab(a);
  const right = rgbToLab(b);
  return Math.hypot(left.l - right.l, left.a - right.a, left.b - right.b);
};

const compositeOver = (foreground: string, alpha: number, background: string): string => {
  const fg = parseColor(foreground);
  const bg = parseColor(background);
  const mix = {
    r: Math.round(fg.r * alpha + bg.r * (1 - alpha)),
    g: Math.round(fg.g * alpha + bg.g * (1 - alpha)),
    b: Math.round(fg.b * alpha + bg.b * (1 - alpha)),
  };
  return `rgb(${mix.r} ${mix.g} ${mix.b})`;
};

/** Approximate `.glass` surface over a worst-case black or white photo sample. */
export const glassSurface = (cell: PaletteCell, photo: "dark" | "light"): string =>
  compositeOver(cell.bg, GLASS_SCRIM_ALPHA, photo === "dark" ? "rgb(0 0 0)" : "rgb(255 255 255)");

/** Detailed contrast report used by tests and the resolver gate. */
export const cellContrastReport = (cell: PaletteCell) => {
  const bodyOnBg = contrastRatio(TEXT, cell.bg);
  const largeUiOnBg = contrastRatio(LARGE_UI, cell.bg);
  const primaryAccentContrast = contrastRatio(cell.p, cell.a);
  const primaryAccentDelta = deltaE76(cell.p, cell.a);
  const focusOnBg = contrastRatio(FOCUS_RING, cell.bg);
  const focusOnGlassLight = contrastRatio(FOCUS_RING, glassSurface(cell, "light"));
  const focusOnGlassDark = contrastRatio(FOCUS_RING, glassSurface(cell, "dark"));
  return {
    bodyOnBg,
    largeUiOnBg,
    primaryAccentContrast,
    primaryAccentDelta,
    focusOnBg,
    focusOnGlassLight,
    focusOnGlassDark,
    bodyOnGlassLight: contrastRatio(TEXT, glassSurface(cell, "light")),
    bodyOnGlassDark: contrastRatio(TEXT, glassSurface(cell, "dark")),
  };
};

/** Returns true only when a palette may enter live rotation. */
export const cellPasses = (cell: PaletteCell): boolean => {
  const report = cellContrastReport(cell);
  return (
    report.bodyOnBg >= 4.5 &&
    report.largeUiOnBg >= 3 &&
    (report.primaryAccentContrast >= 3 || report.primaryAccentDelta >= 20) &&
    report.focusOnBg >= 3 &&
    report.focusOnGlassLight >= 3 &&
    report.focusOnGlassDark >= 3
  );
};

export const glassScrimAlpha = (): number => clamp01(GLASS_SCRIM_ALPHA);
