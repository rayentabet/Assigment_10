import type { ApprovalRequest } from "../../api/types";
import "./ChatPanel.css";

interface ApprovalCardProps {
  approval: ApprovalRequest;
  isBusy: boolean;
  onDecide: (approved: boolean) => void;
}

export function ApprovalCard({ approval, isBusy, onDecide }: ApprovalCardProps) {
  return (
    <div className="card approval-card">
      <p className="card-warning">{approval.reason}</p>
      <dl className="card-fields">
        <dt>Action</dt>
        <dd>{approval.action}</dd>
        <dt>Task</dt>
        <dd>{approval.task}</dd>
      </dl>
      <div className="card-actions">
        <button
          type="button"
          className="sidebar-button primary"
          disabled={isBusy}
          onClick={() => onDecide(true)}
        >
          Approve
        </button>
        <button type="button" className="sidebar-button" disabled={isBusy} onClick={() => onDecide(false)}>
          Reject
        </button>
      </div>
    </div>
  );
}
