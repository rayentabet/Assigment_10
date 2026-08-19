import type { useConversation } from "../../hooks/useConversation";
import "./ActivityPanel.css";
import { DigiKeyConnection } from "./DigiKeyConnection";
import { ProductCards } from "./ProductCards";
import { PurchaseStatusCard } from "./PurchaseStatusCard";
import { ToolTraceList } from "./ToolTraceList";
import { WiringPlanTable } from "./WiringPlanTable";

interface ActivityPanelProps {
  conversation: ReturnType<typeof useConversation>;
}

export function ActivityPanel({ conversation }: ActivityPanelProps) {
  const { wiringPlan, purchaseReference, productCards, toolTrace, routeHistory } = conversation;

  return (
    <aside className="activity-panel">
      <h2>Activity</h2>
      <DigiKeyConnection />
      {wiringPlan && <WiringPlanTable plan={wiringPlan} />}
      {purchaseReference && <PurchaseStatusCard reference={purchaseReference} />}
      <ProductCards cards={productCards} />
      <ToolTraceList toolTrace={toolTrace} routeHistory={routeHistory} />
    </aside>
  );
}
