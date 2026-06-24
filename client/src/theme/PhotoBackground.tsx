import { useState } from "react";

import { useAmbientCell } from "./AmbientProvider";
import { PALETTES, type CellKey } from "./palettes";

type GlobImportMeta = ImportMeta & {
  glob: <T>(
    pattern: string,
    options: { eager: true; query: string; import: "default" },
  ) => Record<string, T>;
};

const assetUrls = (import.meta as GlobImportMeta).glob<string>("../assets/backgrounds/*.jpg", {
  eager: true,
  query: "?url",
  import: "default",
});

const photoUrlFor = (cell: CellKey): string | undefined => assetUrls[`../assets/backgrounds/${cell}.jpg`];

const gradientFor = (cell: CellKey): string => {
  const palette = PALETTES[cell];
  return [
    `radial-gradient(1100px 760px at 50% -10%, color-mix(in srgb, ${palette.p} 20%, transparent), transparent 62%)`,
    `radial-gradient(760px 560px at 88% 18%, color-mix(in srgb, ${palette.a} 12%, transparent), transparent 68%)`,
    `linear-gradient(180deg, ${palette.bg}, color-mix(in srgb, ${palette.bg} 82%, black))`,
  ].join(", ");
};

/** Decorative in-webview photo layer with a local-asset-only loader and gradient fallback. */
export function PhotoBackground() {
  const cell = useAmbientCell();
  const [failedCell, setFailedCell] = useState<CellKey | null>(null);
  const url = failedCell === cell ? undefined : photoUrlFor(cell);
  const backgroundImage = url === undefined ? gradientFor(cell) : `url("${url}")`;

  return (
    <div className="photo-bg" aria-hidden="true">
      <div
        className="photo-bg__image"
        style={{ backgroundImage }}
        data-cell={cell}
        data-mode={url === undefined ? "gradient" : "photo"}
      />
      {url === undefined ? null : (
        <img
          alt=""
          src={url}
          onError={() => setFailedCell(cell)}
          style={{ display: "none" }}
          aria-hidden="true"
        />
      )}
      <div className="photo-bg__dim" />
    </div>
  );
}
