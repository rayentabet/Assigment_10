import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { createLithicMethod, forgetSandboxCard, getPaymentConfig, tokenizeSandboxCard } from "../../api/client";
import type { PaymentConfig, PaymentCredential, PurchaseProposal } from "../../api/types";
import "./ChatPanel.css";

interface PurchaseProposalCardProps {
  proposal: PurchaseProposal;
  isBusy: boolean;
  onDecide: (approved: boolean, paymentCredentialId?: string) => void;
  paymentCredential: PaymentCredential | null;
  onCredentialChange: (credential: PaymentCredential | null) => void;
}

export function PurchaseProposalCard({
  proposal,
  isBusy,
  onDecide,
  paymentCredential,
  onCredentialChange,
}: PurchaseProposalCardProps) {
  const [showPayment, setShowPayment] = useState(false);
  const [cardNumber, setCardNumber] = useState("4242 4242 4242 4242");
  const [expiry, setExpiry] = useState("12/30");
  const [cvv, setCvv] = useState("123");
  const [isTokenizing, setIsTokenizing] = useState(false);
  const [paymentError, setPaymentError] = useState<string | null>(null);
  const [paymentConfig, setPaymentConfig] = useState<PaymentConfig | null>(null);
  useEffect(() => { void getPaymentConfig().then(setPaymentConfig).catch(error =>
    setPaymentError(error instanceof Error ? error.message : String(error))); }, []);

  async function approveWithCard(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsTokenizing(true);
    setPaymentError(null);
    try {
      const credential = await tokenizeSandboxCard({ card_number: cardNumber, expiry, cvv });
      setCardNumber("");
      setExpiry("");
      setCvv("");
      onCredentialChange(credential);
      onDecide(true, credential.payment_method_id);
    } catch (error) {
      setPaymentError(error instanceof Error ? error.message : String(error));
    } finally {
      setIsTokenizing(false);
    }
  }

  async function forgetCard() {
    if (!paymentCredential) return;
    setPaymentError(null);
    try {
      await forgetSandboxCard(paymentCredential.payment_method_id);
      onCredentialChange(null);
      setShowPayment(true);
    } catch (error) {
      setPaymentError(error instanceof Error ? error.message : String(error));
    }
  }

  async function approveWithLithic() {
    setIsTokenizing(true); setPaymentError(null);
    try {
      const credential = await createLithicMethod();
      onCredentialChange(credential);
      onDecide(true, credential.payment_method_id);
    } catch (error) {
      setPaymentError(error instanceof Error ? error.message : String(error));
    } finally { setIsTokenizing(false); }
  }

  return (
    <div className="card purchase-card">
      <p className="card-warning">{proposal.question}</p>
      <dl className="card-fields">
        <dt>Component</dt>
        <dd>{proposal.component_name ?? proposal.component_id} × {proposal.quantity}</dd>
        <dt>Supplier</dt>
        <dd>{proposal.supplier_name ?? "—"}</dd>
        <dt>Unit price</dt>
        <dd>{proposal.unit_price.toFixed(2)} {proposal.currency}</dd>
        {proposal.fees !== null && <><dt>Fees</dt><dd>{proposal.fees.toFixed(2)} {proposal.currency}</dd></>}
        <dt>Total</dt>
        <dd className="total">{proposal.total.toFixed(2)} {proposal.currency}</dd>
        {proposal.delivery_estimate_days !== null && <><dt>Delivery estimate</dt><dd>{proposal.delivery_estimate_days} day(s)</dd></>}
        <dt>Expires</dt>
        <dd>{proposal.expires_at}</dd>
      </dl>

      {paymentCredential && !showPayment && (
        <div className="saved-payment">
          <strong>{paymentCredential.display}</strong>
          <span>Payment method reference (card details remain with the provider)</span>
        </div>
      )}

      {!showPayment && (
        <>
          <div className="card-actions">
            <button
              type="button"
              className="sidebar-button primary"
              disabled={isBusy}
              onClick={() => paymentCredential
                ? onDecide(true, paymentCredential.payment_method_id)
                : setShowPayment(true)}
            >
              {paymentCredential ? "Approve with saved method" : "Approve and add payment method"}
            </button>
            {paymentCredential && (
              <button type="button" className="sidebar-button" disabled={isBusy} onClick={() => setShowPayment(true)}>
                Use another card
              </button>
            )}
            <button type="button" className="sidebar-button" disabled={isBusy} onClick={() => onDecide(false)}>
              Reject
            </button>
          </div>
          {paymentCredential && (
            <button type="button" className="link-button" disabled={isBusy} onClick={forgetCard}>
              Forget saved test card
            </button>
          )}
        </>
      )}

      {showPayment && paymentConfig?.provider === "lithic" && (
        <div className="payment-form">
          <p className="payment-boundary">
            A single-use Lithic Sandbox virtual card will be issued only after approval.
            No card details are shown to the assistant or browser.
          </p>
          {paymentError && <p className="error-text">{paymentError}</p>}
          <button type="button" className="sidebar-button primary"
            disabled={isBusy || isTokenizing} onClick={() => void approveWithLithic()}>
            {isTokenizing ? "Preparing…" : "Approve with Lithic Sandbox"}
          </button>
        </div>
      )}

      {showPayment && paymentConfig?.provider === "sandbox" && (
        <form className="payment-form" onSubmit={approveWithCard}>
          <p className="payment-boundary">
            AP2 sandbox Credential Provider. Card fields are tokenized and never sent to
            the LLM, chat endpoint, A2A agent, DigiKey, logs, or SQLite.
          </p>
          <label>
            Sandbox card number
            <input value={cardNumber} onChange={(event) => setCardNumber(event.target.value)} inputMode="numeric" autoComplete="cc-number" required />
          </label>
          <div className="payment-row">
            <label>
              Expiry
              <input value={expiry} onChange={(event) => setExpiry(event.target.value)} autoComplete="cc-exp" placeholder="MM/YY" required />
            </label>
            <label>
              CVV
              <input value={cvv} onChange={(event) => setCvv(event.target.value)} inputMode="numeric" autoComplete="cc-csc" type="password" required />
            </label>
          </div>
          <p className="muted">Demo values: 4242 4242 4242 4242 · 12/30 · 123</p>
          {paymentError && <p className="error-text">{paymentError}</p>}
          <div className="card-actions">
            <button className="sidebar-button primary" disabled={isBusy || isTokenizing}>
              {isTokenizing ? "Tokenizing…" : "Tokenize and approve"}
            </button>
            <button type="button" className="sidebar-button" disabled={isBusy || isTokenizing} onClick={() => setShowPayment(false)}>
              Back
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
