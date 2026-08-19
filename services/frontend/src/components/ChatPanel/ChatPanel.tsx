import { artifactUrl } from "../../api/client";
import type { useConversation } from "../../hooks/useConversation";
import { ApprovalCard } from "./ApprovalCard";
import "./ChatPanel.css";
import { MessageInput } from "./MessageInput";
import { MessageList } from "./MessageList";
import { PurchaseProposalCard } from "./PurchaseProposalCard";

interface ChatPanelProps {
  conversation: ReturnType<typeof useConversation>;
}

export function ChatPanel({ conversation }: ChatPanelProps) {
  const {
    threadId,
    messages,
    imageUrls,
    pendingApproval,
    pendingPurchaseProposal,
    paymentCredential,
    isSending,
    error,
    isLoadingHistory,
    historyError,
    send,
    resume,
    setPaymentCredential,
  } = conversation;

  const awaitingDecision = pendingApproval !== null || pendingPurchaseProposal !== null;

  return (
    <section className="chat-panel">
      <div className="chat-scroll">
        {isLoadingHistory && <p className="muted">Loading conversation…</p>}
        {historyError && <p className="error-text">{historyError}</p>}
        <MessageList messages={messages} />

        {imageUrls.length > 0 && (
          <div className="image-gallery">
            {imageUrls.map((url) => (
              <img key={url} src={artifactUrl(url)} alt="Agent-generated artifact" />
            ))}
          </div>
        )}

        {pendingApproval && (
          <ApprovalCard approval={pendingApproval} isBusy={isSending} onDecide={resume} />
        )}
        {pendingPurchaseProposal && (
          <PurchaseProposalCard
            proposal={pendingPurchaseProposal}
            isBusy={isSending}
            onDecide={resume}
            paymentCredential={paymentCredential}
            onCredentialChange={setPaymentCredential}
          />
        )}

        {isSending && !awaitingDecision && <p className="muted">The agent is working…</p>}
        {error && <p className="error-text">{error}</p>}
      </div>

      <MessageInput
        disabled={isSending || awaitingDecision || isLoadingHistory}
        placeholder={
          awaitingDecision
            ? "Resolve the pending approval above first…"
            : "Ask about robotics, Arduino code, wiring, or a purchase…"
        }
        threadId={threadId}
        onSend={send}
      />
    </section>
  );
}
