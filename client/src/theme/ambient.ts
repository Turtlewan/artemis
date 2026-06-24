import { cellPasses } from "./contrast";
import {
  GLOBAL_DEFAULT_CELL,
  PALETTES,
  TIME_STATES,
  cellKey,
  type CellKey,
  type Season,
  type TimeState,
} from "./palettes";

type StyleRoot = { style: Pick<CSSStyleDeclaration, "setProperty"> };

const SAME_SEASON_FALLBACK_ORDER: readonly TimeState[] = [
  "afternoon",
  "morning",
  "evening",
  "night",
];

const minutesSinceMidnight = (date: Date): number => date.getHours() * 60 + date.getMinutes();

/** Northern-hemisphere aesthetic season mapping by month. */
export const seasonForDate = (date: Date): Season => {
  const month = date.getMonth();
  if (month >= 2 && month <= 4) return "Spring";
  if (month >= 5 && month <= 7) return "Summer";
  if (month >= 8 && month <= 10) return "Autumn";
  return "Winter";
};

/** Quiet-hours night is 23:30-07:15; the waking window is split into thirds. */
export const timeStateForDate = (date: Date): TimeState => {
  const minutes = minutesSinceMidnight(date);
  if (minutes >= 23 * 60 + 30 || minutes < 7 * 60 + 15) return "night";
  if (minutes < 12 * 60 + 40) return "morning";
  if (minutes < 18 * 60 + 5) return "afternoon";
  return "evening";
};

const verified = (key: CellKey): boolean => {
  const cell = PALETTES[key];
  return cell.vetted && cellPasses(cell);
};

const nearestVerifiedCell = (season: Season): CellKey => {
  for (const time of SAME_SEASON_FALLBACK_ORDER) {
    const key = cellKey(season, time);
    if (verified(key)) return key;
  }

  if (verified(GLOBAL_DEFAULT_CELL)) return GLOBAL_DEFAULT_CELL;

  const firstVerified = (Object.keys(PALETTES) as CellKey[]).find(verified);
  return firstVerified ?? GLOBAL_DEFAULT_CELL;
};

/** Resolves the ambient cell for a clock instant, gating out draft or failing cells. */
export const resolveCell = (date: Date): CellKey => {
  const season = seasonForDate(date);
  const key = cellKey(season, timeStateForDate(date));
  return verified(key) ? key : nearestVerifiedCell(season);
};

/** Returns the ungated season-time target, useful for tests and diagnostics. */
export const resolveRawCell = (date: Date): CellKey =>
  cellKey(seasonForDate(date), timeStateForDate(date));

/** Applies the active palette tokens to a root element. */
export const applyCell = (cell: CellKey, root: StyleRoot = document.documentElement): void => {
  const palette = PALETTES[cell];
  root.style.setProperty("--bg", palette.bg);
  root.style.setProperty("--p", palette.p);
  root.style.setProperty("--a", palette.a);
};

/** All possible cells in stable matrix order. */
export const allCellKeys = (): CellKey[] =>
  (["Spring", "Summer", "Autumn", "Winter"] as const).flatMap((season) =>
    TIME_STATES.map((time) => cellKey(season, time)),
  );
