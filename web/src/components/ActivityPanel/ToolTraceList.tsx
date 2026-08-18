import type { ToolTraceEntry } from "../../api/types";
import "./ActivityPanel.css";

interface ToolTraceListProps {
  toolTrace: ToolTraceEntry[];
  routeHistory: string[];
}

export function ToolTraceList({ toolTrace, routeHistory }: ToolTraceListProps) {
  return (
    <div className="activity-block">
      <h3>Last turn's activity</h3>
      {routeHistory.length > 0 && (
        <p className="route-breadcrumb">{routeHistory.join(" → ")}</p>
      )}
      {toolTrace.length === 0 ? (
        <p className="muted small">No tool activity for the last message.</p>
      ) : (
        <ul className="trace-list">
          {toolTrace.map((entry, index) => (
            <li key={index} className={`trace-entry trace-${entry.event}`}>
              <span className="trace-agent">{entry.agent}</span>
              <span className="trace-tool">{entry.tool}</span>
              <span className="trace-event">{entry.event}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
