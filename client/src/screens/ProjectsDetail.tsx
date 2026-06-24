import type { DomainDetailProps } from "../card/types";
import { DomainDetailShell, EngineTagText } from "./DomainDetailShell";
import type { ProjectsRead } from "./dtos";
import { useDomainRead, type DomainReader } from "./useDomainRead";

interface ProjectsDetailProps extends DomainDetailProps {
  reader?: DomainReader<ProjectsRead>;
}

const statusLabel = (status: "active" | "blocked" | "done"): string =>
  status === "active" ? "Active" : status === "blocked" ? "Blocked" : "Done";

export function ProjectsDetail({ domainId, onClose, reader }: ProjectsDetailProps) {
  const { data, loading, error } = useDomainRead<ProjectsRead>(domainId, reader);

  return (
    <DomainDetailShell
      domainId={domainId}
      title="Projects"
      engine={<EngineTagText value="local" />}
      loading={loading}
      error={error}
      empty={data !== null && data.projects.length === 0 ? "No active projects." : null}
      onClose={onClose}
    >
      {data !== null && (
        <ul className="screen-list" role="list">
          {data.projects.map((project) => (
            <li className="screen-row" key={project.id}>
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <strong style={{ flex: 1 }}>{project.name}</strong>
                <span className={`screen-pill project-status-${project.status}`}>{statusLabel(project.status)}</span>
                <span className="screen-muted">{project.target ?? "No target"}</span>
                <span className="screen-pill">{project.openTasks} open tasks</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </DomainDetailShell>
  );
}
