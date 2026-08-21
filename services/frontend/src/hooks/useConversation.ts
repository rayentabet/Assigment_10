// Orchestrates one conversation's request/response state: message history,
// live per-node progress while a turn is running, and pending approvals.
// send/resume stream over SSE (see api/client.ts's streamMessage/streamResume)
// so the Activity panel updates as each graph node completes, instead of
// only once the whole turn finishes or pauses.

import { useCallback, useEffect, useState } from "react";

import { streamMessage, streamResume } from "../api/client";
import { useThreadHistoryQuery } from "../api/hooks";
import type {
  ApprovalRequest,
  ChatResponse,
  PaymentCredential,
  PurchaseProposal,
  PurchaseReference,
  ProductCard,
  StreamFrame,
  StreamNodeFrame,
  ToolTraceEntry,
  WiringPlan,
} from "../api/types";

export interface DisplayMessage {
  role: "user" | "assistant";
  content: string;
  imageUrls?: string[];
}

export function useConversation(threadId: string | null) {
  const history = useThreadHistoryQuery(threadId);

  const [messages, setMessages] = useState<DisplayMessage[]>([]);
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
  const [currentNode, setCurrentNode] = useState<string | null>(null);

  // Reset per-turn state whenever a different thread's history loads; the
  // API only ever reports the *last* turn's activity (no SSE event log), so
  // tool trace / pending approvals from a previous thread must not leak in.
  useEffect(() => {
    if (!history.data) return;
    const loaded: DisplayMessage[] = history.data.messages.map((m) => ({
      role: m.role,
      content: m.content,
    }));
    // The history endpoint returns the thread's images as one flat list, not
    // tied to a specific message, so attach them to the last assistant
    // message rather than rendering a separate trailing gallery that would
    // drift further down the page as the conversation grows.
    if (history.data.image_urls.length > 0) {
      for (let i = loaded.length - 1; i >= 0; i--) {
        if (loaded[i].role === "assistant") {
          loaded[i] = { ...loaded[i], imageUrls: history.data.image_urls };
          break;
        }
      }
    }
    setMessages(loaded);
    setWiringPlan(history.data.wiring_plan);
    setPurchaseReference(history.data.purchase_reference);
    setProductCards(history.data.product_cards);
    setToolTrace([]);
    setRouteHistory([]);
    setPendingApproval(null);
    setPendingPurchaseProposal(null);
    setError(null);
    setCurrentNode(null);
  }, [history.data]);

  const applyResponse = useCallback((response: ChatResponse) => {
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
      setMessages((previous) => {
        // response.image_urls is the thread's full cumulative list, so only
        // attach the ones this message hasn't already shown.
        const alreadyShown = new Set(previous.flatMap((m) => m.imageUrls ?? []));
        const newImageUrls = response.image_urls.filter((url) => !alreadyShown.has(url));
        return [
          ...previous,
          {
            role: "assistant",
            content: answer,
            ...(newImageUrls.length > 0 ? { imageUrls: newImageUrls } : {}),
          },
        ];
      });
    }
  }, []);

  // Each "node" frame's tool_trace/route_history is already the full
  // accumulated list-so-far (the graph nodes build them that way), so this
  // is a plain replace, not an append.
  const applyNodeFrame = useCallback((update: StreamNodeFrame) => {
    setCurrentNode(update.node);
    if (update.update.tool_trace) setToolTrace(update.update.tool_trace);
    if (update.update.route_history) setRouteHistory(update.update.route_history);
  }, []);

  const consumeStream = useCallback(
    async (frames: AsyncGenerator<StreamFrame>) => {
      for await (const frame of frames) {
        if (frame.type === "node") {
          applyNodeFrame(frame);
        } else if (frame.type === "done") {
          applyResponse(frame);
        } else {
          setError(frame.message);
        }
      }
    },
    [applyNodeFrame, applyResponse],
  );

  const send = useCallback(
    async (message: string) => {
      if (!threadId || isSending) return;
      setMessages((previous) => [...previous, { role: "user", content: message }]);
      setIsSending(true);
      setError(null);
      setCurrentNode(null);
      try {
        await consumeStream(streamMessage(threadId, message));
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setIsSending(false);
        setCurrentNode(null);
      }
    },
    [threadId, isSending, consumeStream],
  );

  const resume = useCallback(
    async (approved: boolean, paymentCredentialId?: string) => {
      if (!threadId || isSending) return;
      setIsSending(true);
      setError(null);
      setCurrentNode(null);
      // Clear the decision immediately so the approval/purchase card is
      // replaced by the live "Running <node>…" status right away, instead
      // of sitting there disabled for the whole resumed turn (that status
      // line is hidden while a decision is still pending).
      setPendingApproval(null);
      setPendingPurchaseProposal(null);
      try {
        await consumeStream(streamResume(threadId, approved, paymentCredentialId));
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setIsSending(false);
        setCurrentNode(null);
      }
    },
    [threadId, isSending, consumeStream],
  );

  return {
    threadId,
    messages,
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
    currentNode,
    isLoadingHistory: history.isLoading,
    historyError: history.error instanceof Error ? history.error.message : null,
    send,
    resume,
    setPaymentCredential,
  };
}
