import type { PurchaseReference } from "../../api/types";
import "./ActivityPanel.css";

interface PurchaseStatusCardProps {
  reference: PurchaseReference;
}

export function PurchaseStatusCard({ reference }: PurchaseStatusCardProps) {
  return (
    <div className="activity-block">
      <div className="activity-block-header">
        <h3>Latest order</h3>
        {reference.status && <span className="badge badge-neutral">{reference.status}</span>}
      </div>
      <dl className="card-fields">
        {reference.order_id && (
          <>
            <dt>Order</dt>
            <dd>{reference.order_id}</dd>
          </>
        )}
        {reference.proposal_id && (
          <>
            <dt>Proposal</dt>
            <dd>{reference.proposal_id}</dd>
          </>
        )}
      </dl>
      <p className="muted small">
        Price and supplier detail live only in the Component Manager's own records.
      </p>
    </div>
  );
}
