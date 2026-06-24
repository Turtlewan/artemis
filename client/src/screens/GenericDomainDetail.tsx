import type { DomainDetailProps } from "../card/types";
import { domainLabel } from "../domains";
import { DomainDetailShell, EngineTagText } from "./DomainDetailShell";
import type { GenericRead } from "./dtos";
import { useDomainRead, type DomainReader } from "./useDomainRead";

interface GenericDomainDetailProps extends DomainDetailProps {
  reader?: DomainReader<GenericRead>;
}

export function GenericDomainDetail({ domainId, onClose, reader }: GenericDomainDetailProps) {
  const { data, loading, error } = useDomainRead<GenericRead>(domainId, reader);
  const unavailable = data === null && !loading && error === null ? "Data not yet available for this domain." : null;

  return (
    <DomainDetailShell
      domainId={domainId}
      title={domainLabel(domainId)}
      engine={<EngineTagText value="local" />}
      loading={loading}
      error={error}
      empty={unavailable}
      onClose={onClose}
    >
      {data !== null && (
        <>
          <h2>{data.count} items</h2>
          <ul className="screen-list" role="list">
            {data.items.map((item) => (
              <li className="screen-row" key={`${item.title}-${item.subtitle ?? ""}`}>
                <strong>{item.title}</strong>
                {item.subtitle !== undefined && <p className="screen-muted">{item.subtitle}</p>}
                {item.engine !== undefined && <EngineTagText value={item.engine} />}
              </li>
            ))}
          </ul>
          <p role="status" aria-live="polite" className="screen-status">
            Data not yet available for this domain.
          </p>
        </>
      )}
    </DomainDetailShell>
  );
}
