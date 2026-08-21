# Lithic Sandbox credential provider

## Environment

```dotenv
APP_ENVIRONMENT=development
PAYMENT_PROVIDER=lithic
LITHIC_API_KEY=your-sandbox-api-key
LITHIC_BASE_URL=https://sandbox.lithic.com/v1
LITHIC_TIMEOUT_SECONDS=20
```

`LITHIC_API_KEY` is backend-only. It is never returned by an API route or
included in application logs. The provider rejects any non-sandbox base URL.
The optional legacy local provider requires `PAYMENT_PROVIDER=sandbox` and
`APP_ENVIRONMENT=development`.

## Data flow

1. ADK creates a DigiKey proposal and AP2 evidence.
2. React creates a safe local `pm_...` handle; no Lithic API call occurs yet.
3. Human approval resumes LangGraph with only `pm_...`.
4. `PaymentService` validates user/thread, merchant, amount, currency, items,
   expiry, nonce and replay state.
5. `PaymentService` asks `LithicCredentialProvider` for a single-use virtual
   card limited to the approved amount.
6. The provider submits the PAN directly to Lithic's sandbox authorization
   simulator. PAN, CVV, card token and raw responses remain inside the provider.
7. A sanitized `lithic_sandbox_authorized` marker reaches the deterministic
   DigiKey sandbox order endpoint, which independently revalidates proposal
   expiry, approval signature and database idempotency before ordering.
8. LangGraph receives only `pm_...`, masked display, order ID and status.

## Important limitation

Lithic Sandbox is not connected to payment networks. Its authorization is a
simulation and DigiKey's sandbox Ordering API does not accept card details.
The paired authorization/order flow proves orchestration and security boundaries;
it is not a real DigiKey payment and is not production-ready for Lebanon.

## Tests

```bash
PYTHONPATH=services/agent-system-a .venv/bin/pytest -q \
  tests/test_payment_vault.py tests/test_payment_service.py tests/test_api.py tests/test_graph.py
PYTHONPATH=services/agent-system-b .venv/bin/pytest -q \
  tests/component_manager/test_ordering.py
cd services/frontend && npm run build
```
