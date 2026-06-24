import { EngineTag, type AskEngine } from "./EngineTag";

interface ResultRowProps {
  title: string;
  subtitle: string;
  engine: AskEngine;
  failedLocked?: boolean;
}

/** One Ask result row with decorative mark, text summary, and load-bearing engine tag. */
export function ResultRow({ title, subtitle, engine, failedLocked = false }: ResultRowProps) {
  return (
    <li className="ask-result-row" tabIndex={0} data-locked={failedLocked ? "true" : "false"}>
      <span className="ask-result-row__icon" aria-hidden="true">
        <span />
      </span>
      <span className="ask-result-row__copy">
        <span className="ask-result-row__title">{title}</span>
        <span className="ask-result-row__subtitle">{subtitle}</span>
      </span>
      <EngineTag engine={engine} />
    </li>
  );
}
