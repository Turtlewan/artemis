/** Season axis used by the 4x4 ambient palette matrix. */
export type Season = "Spring" | "Summer" | "Autumn" | "Winter";

/** Clock-state axis used by the 4x4 ambient palette matrix. */
export type TimeState = "morning" | "afternoon" | "evening" | "night";

/** `${Season}-${TimeState}` key for one ambient palette cell. */
export type CellKey = `${Season}-${TimeState}`;

/** One design-brief palette cell. Draft cells are excluded from live rotation. */
export type PaletteCell = {
  bg: string;
  p: string;
  a: string;
  vetted: boolean;
};

export const SEASONS = ["Spring", "Summer", "Autumn", "Winter"] as const satisfies readonly Season[];

export const TIME_STATES = [
  "morning",
  "afternoon",
  "evening",
  "night",
] as const satisfies readonly TimeState[];

/** Fixed fallback used if no same-season verified cell is available. */
export const GLOBAL_DEFAULT_CELL: CellKey = "Winter-afternoon";

/** Source-of-truth design-brief matrix. Hex literals are intentionally centralized here. */
export const PALETTES: Record<CellKey, PaletteCell> = {
  "Spring-morning": { bg: "#08120e", p: "#8fecb8", a: "#ffc2a6", vetted: true },
  "Spring-afternoon": { bg: "#0a1612", p: "#5fee9c", a: "#84d2ff", vetted: true },
  "Spring-evening": { bg: "#0a0c0d", p: "#f2b487", a: "#93d59a", vetted: true },
  "Spring-night": { bg: "#05080f", p: "#5aa6d0", a: "#8fd0a8", vetted: false },
  "Summer-morning": { bg: "#0e0a10", p: "#ff9e6e", a: "#8fb0ff", vetted: false },
  "Summer-afternoon": { bg: "#11140a", p: "#ffd64a", a: "#58c4f2", vetted: false },
  "Summer-evening": { bg: "#0d0908", p: "#ff9f4a", a: "#ff5e8a", vetted: false },
  "Summer-night": { bg: "#06080f", p: "#4f9fc8", a: "#e3a06f", vetted: false },
  "Autumn-morning": { bg: "#0f0c08", p: "#e3b572", a: "#93b39c", vetted: true },
  "Autumn-afternoon": { bg: "#100a05", p: "#f0a23f", a: "#c2552b", vetted: true },
  "Autumn-evening": { bg: "#0d0606", p: "#ff7338", a: "#9a5ab0", vetted: true },
  "Autumn-night": { bg: "#0a0707", p: "#a06a44", a: "#6a5a7a", vetted: false },
  "Winter-morning": { bg: "#080d14", p: "#abe0ff", a: "#ffc7a6", vetted: true },
  "Winter-afternoon": { bg: "#060c14", p: "#58c6ff", a: "#fff0d8", vetted: true },
  "Winter-evening": { bg: "#07091a", p: "#8aa6ff", a: "#ffb479", vetted: true },
  "Winter-night": { bg: "#05070e", p: "#5a76b0", a: "#b88a5c", vetted: false },
};

/** Builds the canonical palette key without widening the template-literal type. */
export const cellKey = (season: Season, time: TimeState): CellKey => `${season}-${time}`;
