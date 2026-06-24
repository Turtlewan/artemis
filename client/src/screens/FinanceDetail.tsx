import { useState } from "react";

import type { DomainDetailProps } from "../card/types";
import { DomainDetailShell, EngineTagText } from "./DomainDetailShell";
import type { FinanceRead } from "./dtos";
import { useDomainRead, type DomainReader } from "./useDomainRead";

interface FinanceDetailProps extends DomainDetailProps {
  reader?: DomainReader<FinanceRead>;
}

const money = (amount: number): string => `${amount < 0 ? "-" : ""}S$${Math.abs(amount).toFixed(2)}`;

const donutPath = (startPct: number, endPct: number): string => {
  const radius = 44;
  const center = 60;
  const start = startPct * Math.PI * 2 - Math.PI / 2;
  const end = endPct * Math.PI * 2 - Math.PI / 2;
  const sx = center + Math.cos(start) * radius;
  const sy = center + Math.sin(start) * radius;
  const ex = center + Math.cos(end) * radius;
  const ey = center + Math.sin(end) * radius;
  return `M ${center} ${center} L ${sx} ${sy} A ${radius} ${radius} 0 ${endPct - startPct > 0.5 ? 1 : 0} 1 ${ex} ${ey} Z`;
};

export function FinanceDetail({ domainId, onClose, reader }: FinanceDetailProps) {
  const { data, loading, error } = useDomainRead<FinanceRead>(domainId, reader);
  const [paid, setPaid] = useState<Set<string>>(new Set());
  const [message, setMessage] = useState("");
  let cursor = 0;

  const mark = (name: string): void => {
    setPaid((current) => new Set(current).add(name));
    setMessage(`${name} marked paid locally.`);
  };

  return (
    <DomainDetailShell
      domainId={domainId}
      title="Finance"
      engine={<EngineTagText value="local" />}
      loading={loading}
      error={error}
      empty={data !== null && data.daily.length === 0 ? "No finance data." : null}
      onClose={onClose}
    >
      {data !== null && (
        <div className="screen-split">
          <div>
            <p>
              Week <strong>{money(data.week_total)}</strong> · MTD <strong>{money(data.mtd_total)}</strong>
            </p>
            <h3 className="screen-eyebrow">Daily spend</h3>
            <ul className="screen-list" role="list" aria-label="Daily spend">
              {data.daily.map((day) => (
                <li className="screen-row" key={day.date}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span>
                      {day.weekday} {day.date}
                    </span>
                    <strong>{day.amount === null ? "—" : money(day.amount)}</strong>
                  </div>
                  {day.is_today && <div data-testid="today-divider" style={{ height: 1, background: "var(--a)", marginTop: 6 }} />}
                </li>
              ))}
            </ul>
            <h3 className="screen-eyebrow">Bills</h3>
            <ul className="screen-list" role="list" aria-label="Bills">
              {data.bills.map((bill) => (
                <li className="screen-row" key={bill.name}>
                  <strong>{bill.name}</strong> <span className="screen-muted">{bill.when}</span>{" "}
                  <span className="screen-pill">{bill.overdue ? "overdue" : "due"}</span> {money(bill.amount)}
                  <button className="screen-btn" type="button" onClick={() => mark(bill.name)}>
                    {bill.paid || paid.has(bill.name) ? "Paid" : "Mark paid"}
                  </button>
                </li>
              ))}
            </ul>
            <p role="status" aria-live="polite" className="screen-status">
              {message}
            </p>
          </div>
          <aside>
            <h3 className="screen-eyebrow">Category</h3>
            <svg width="260" height="150" viewBox="0 0 260 150" role="img" aria-label="Category donut with leader lines">
              {data.categories.map((category, index) => {
                const start = cursor;
                const end = cursor + category.pct / 100;
                cursor = end;
                const mid = ((start + end) / 2) * Math.PI * 2 - Math.PI / 2;
                const x1 = 60 + Math.cos(mid) * 48;
                const y1 = 60 + Math.sin(mid) * 48;
                const x2 = 145;
                const y2 = 20 + index * 22;
                return (
                  <g key={category.name}>
                    <path d={donutPath(start, end)} fill={category.color} opacity="0.78" />
                    <line x1={x1} y1={y1} x2={x2 - 8} y2={y2 - 4} stroke="var(--hair)" />
                    <text x={x2} y={y2} fill="currentColor" fontSize="11">
                      {category.name} {category.pct}%
                    </text>
                  </g>
                );
              })}
              <circle cx="60" cy="60" r="25" fill="var(--bg)" />
              <text x="60" y="58" textAnchor="middle" fill="currentColor" fontSize="11">
                Total
              </text>
              <text x="60" y="72" textAnchor="middle" fill="currentColor" fontSize="11">
                {money(data.week_total)}
              </text>
            </svg>
            <h3 className="screen-eyebrow">Transactions</h3>
            <ul className="screen-list" role="list">
              {data.transactions.map((txn) => (
                <li className="screen-row" key={`${txn.date}-${txn.merchant}`}>
                  {txn.date} · {txn.merchant} · {txn.category} · {money(txn.amount)}
                </li>
              ))}
            </ul>
            {data.unusual !== null && (
              <section>
                <h3 className="screen-eyebrow">Unusual spend</h3>
                <p>
                  {data.unusual.merchant} {money(data.unusual.amount)} - {data.unusual.why}
                </p>
                <button className="screen-btn" type="button" onClick={() => setMessage("Recategorised locally.")}>
                  Recategorise
                </button>{" "}
                <button className="screen-btn" type="button" onClick={() => setMessage("Marked looks right.")}>
                  Looks right
                </button>
              </section>
            )}
            {data.duplicate !== null && (
              <section>
                <h3 className="screen-eyebrow">Duplicate merge</h3>
                <p>{data.duplicate.why}</p>
                <button className="screen-btn" type="button" onClick={() => setMessage("Kept both locally.")}>
                  Keep both
                </button>{" "}
                <button className="screen-btn" type="button" onClick={() => setMessage("Merged locally.")}>
                  Merge
                </button>
              </section>
            )}
            {data.ambiguous !== null && (
              <section>
                <h3 className="screen-eyebrow">Confirm type</h3>
                <p>
                  {data.ambiguous.merchant} {money(data.ambiguous.amount)} - {data.ambiguous.why}
                </p>
                <button className="screen-btn" type="button" onClick={() => setMessage("Marked transfer locally.")}>
                  Transfer
                </button>{" "}
                <button className="screen-btn" type="button" onClick={() => setMessage("Marked income locally.")}>
                  Income
                </button>
              </section>
            )}
          </aside>
        </div>
      )}
    </DomainDetailShell>
  );
}
