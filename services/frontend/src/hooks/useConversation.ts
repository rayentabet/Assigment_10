// Orchestrates one conversation's request/response state: message history,
// the last turn's images/wiring plan/purchase state, and pending approvals.
// Deliberately request/response, not SSE (see project decisions) — every
// send/resume call blocks until the graph run finishes or pauses.

import { useCallback, useEffect, useState } from "react";

import { resumeThread, sendMessage } from "../api/client";
import { useThreadHistoryQuery } from "../api/hooks";
import type {
  ApprovalRequest,
  ChatResponse,
  PaymentCredential,
  PurchaseProposal,
  PurchaseReference,
  ProductCard,
  ToolTraceEntry,
  WiringPlan,
} from "../api/types";

export interface DisplayMessage {
  role: "user" | "assistant";
  content: string;
}

export function useConversation(threadId: string | null) {
  const history = useThreadHistoryQuery(threadId);

  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [imageUrls, setImageUrls] = useState<string[]>([]);
  const [wiringPlan, setWiringPlan] = useState<WiringPlan | null>(null);
  const [purchaseReference, setPurchaseReference] = useState<PurchaseReference | null>(null);
  const [productCards, setProductCards] = useState<ProductCard[]>([]);
  const [toolTrace, setToolTrace] = useState<ToolTraceEntry[]>([]);
  const [routeHistory, setRouteHistory] = useState<string[]>([]);
  const [pendingApproval, setPendingApproval] = useState<ApprovalRequest | null>(null);
  const [pendingPurchaseProposal, setPendingPurchaseProposal] = useState<PurchaseProposal | null>(
    null,
  );
  const [paymentCredential, setPaymentCredential] = useState<PaymentCredential | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Reset per-turn state whenever a different thread's history loads; the
  // API only ever reports the *last* turn's activity (no SSE event log), so
  // tool trace / pending approvals from a previous thread must not leak in.
  useEffect(() => {
    if (!history.data) return;
    setMessages(history.data.messages.map((m) => ({ role: m.role, content: m.content })));
    setImageUrls(history.data.image_urls);
    setWiringPlan(history.data.wiring_plan);
    setPurchaseReference(history.data.purchase_reference);
    setProductCards(history.data.product_cards);
    setToolTrace([]);
    setRouteHistory([]);
    setPendingApproval(null);
    setPendingPurchaseProposal(null);
    setError(null);
  }, [history.data]);

  const applyResponse = useCallback((response: ChatResponse) => {
    setImageUrls((previous) => Array.from(new Set([...previous, ...response.image_urls])));
    if (response.wiring_plan) setWiringPlan(response.wiring_plan);
    if (response.purchase_reference) setPurchaseReference(response.purchase_reference);
    setProductCards(response.product_cards);
    setToolTrace(response.tool_trace);
    setRouteHistory(response.route_history);

    if (response.status === "approval_required") {
      setPendingApproval(response.approval);
      setPendingPurchaseProposal(response.purchase_proposal);
      return;
    }

    setPendingApproval(null);
    setPendingPurchaseProposal(null);
    if (response.answer) {
      const answer = response.answer;
      setMessages((previous) => [...previous, { role: "assistant", content: answer }]);
    }
  }, []);

  const send = useCallback(
    async (message: string) => {
      if (!threadId || isSending) return;
      setMessages((previous) => [...previous, { role: "user", content: message }]);
      setIsSending(true);
      setError(null);
      try {
        applyResponse(await sendMessage(threadId, message));
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setIsSending(false);
      }
    },
    [threadId, isSending, applyResponse],
  );

  const resume = useCallback(
    async (approved: boolean, paymentCredentialId?: string) => {
      if (!threadId || isSending) return;
      setIsSending(true);
      setError(null);
      try {
        applyResponse(await resumeThread(threadId, approved, paymentCredentialId));
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setIsSending(false);
      }
    },
    [threadId, isSending, applyResponse],
  );

  return {
    threadId,
    messages,
    imageUrls,
    wiringPlan,
    purchaseReference,
    productCards,
    toolTrace,
    routeHistory,
    pendingApproval,
    pendingPurchaseProposal,
    paymentCredential,
    isSending,
    error,
    isLoadingHistory: history.isLoading,
    historyError: history.error instanceof Error ? history.error.message : null,
    send,
    resume,
    setPaymentCredential,
  };
}
