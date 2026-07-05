export type AskEngine = "local" | "codex" | "review" | "loop";

interface EngineTagProps {
  engine: AskEngine;
}

/** Text-bearing engine provenance tag; the visible word is the contract. */
export function EngineTag({ engine }: EngineTagProps) {
  return (
    <span
      className={`ask-engine-tag ask-engine-tag--${engine}`}
      data-engine={engine}
      aria-label={`engine: ${engine}`}
    >
      {engine}
    </span>
  );
}
