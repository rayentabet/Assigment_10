import type { WiringPlan } from "../../api/types";
import "./ActivityPanel.css";

interface WiringPlanTableProps {
  plan: WiringPlan;
}

export function WiringPlanTable({ plan }: WiringPlanTableProps) {
  const rows = plan.components.flatMap((component) =>
    Object.entries(component.pins).map(([pinName, pinValue]) => ({
      key: `${component.component}-${pinName}`,
      display_name: component.display_name,
      pinName,
      pinValue,
    })),
  );

  return (
    <div className="activity-block">
      <div className="activity-block-header">
        <h3>Wiring plan</h3>
        <span className={`badge ${plan.valid ? "badge-ok" : "badge-error"}`}>
          {plan.valid ? "Valid" : "Conflicts"}
        </span>
      </div>
      <p className="muted">{plan.board}</p>
      {rows.length > 0 && (
        <table className="wiring-table">
          <thead>
            <tr>
              <th>Component</th>
              <th>Pin</th>
              <th>Board pin</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                <td>{row.display_name}</td>
                <td>{row.pinName}</td>
                <td>{row.pinValue}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {plan.conflicts.length > 0 && (
        <ul className="issue-list issue-error">
          {plan.conflicts.map((conflict) => (
            <li key={conflict}>{conflict}</li>
          ))}
        </ul>
      )}
      {plan.warnings.length > 0 && (
        <ul className="issue-list issue-warning">
          {plan.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
