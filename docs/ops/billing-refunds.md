# Billing refunds

Status: Current

Credits are non-refundable except where required by law or when an operator
approves a documented exception. Automatic reversal is deliberately limited to
a purchase with no later settled debit; anything ambiguous stops for manual
ledger review.

## Approved unused-credit exception

1. Confirm the requester, payment intent, reason, and applicable policy.
2. Confirm Stripe and the credit ledger identify the same user and amount.
3. Call `POST /api/ops/billing/refunds` with the operations token and:
   `payment_intent_id`, `operator`, and `reason`.
4. Record the returned Stripe refund ID and credits reversed.
5. Confirm `credit_refunds.status = completed`, the compensating ledger debit
   exists, and the customer balance no longer includes the reversed grant.

Retries are safe: the payment intent, Stripe idempotency key, refund ID, and
ledger refund ID are unique.

## Recovery states

- HTTP 409: credits may have been consumed or ownership is ambiguous. Do not
  refund automatically; reconcile Stripe, the complete ledger, and customer
  communications manually.
- HTTP 503 after Stripe acceptance: retry the identical operation. The durable
  refund row and Stripe idempotency key recover the compensating ledger write.
- Stripe HTTP 429/5xx before acceptance: the pending negative ledger hold
  remains reserved so the credits cannot be spent during recovery. Retry the
  identical operation. Before manually releasing a stuck hold, verify in
  Stripe that no refund was accepted.
- Never create a manual positive adjustment to “fix” a refund. Resolve the
  durable refund record and its single negative ledger row.
