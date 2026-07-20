# Slice 0 — Founding Author Lab External Decisions and Operator Contract

Status: Proposed (2026-07-20)

## Problem Statement

Scenewright is not yet ready to admit paying authors because several facts cannot be inferred safely from application code: whether the name may be used for a limited pilot, what exactly the author is buying, who responds when something goes wrong, and which support, legal, billing, and data-handling promises are real. If these decisions remain implicit, the application can make a customer-facing claim that the operator cannot honor.

The initial product is a controlled, invite-only Founding Author Lab for no more than ten paying authors, admitted in waves of two. The pilot is operated by one person and is not a zero-touch public launch.

## Solution

Lock the external pilot contract and operating policy before customer-facing work proceeds. Obtain a written practitioner recommendation on the SceneWrite/Scenewright conflict risk for the United States, Canada, and a practical screen for the locations of invited authors. Record only a non-sensitive use/rename decision in the repository; keep privileged advice private.

Define the commercial offer as repeatable $12 Starter purchases of 1,200 non-expiring credits. Credits are the product contract. A 6–12-page visual reader magnet or first-chapter issue is an illustrative use case and marketing hook, not a guaranteed deliverable, quota, or domain object. Authors see server-sourced price and credit information before generation and may purchase additional identical Starter packs.

Define manual admission, rights attestation, English pilot support, capacity reservation, refund exceptions, operator ownership, mailbox routing, response targets, privacy boundaries, consent, and offer-version recording. Continue engineering and internal testing behind gates while name clearance is pending, but do not conduct customer outreach, paid transactions, public promotion, or activate customer-facing offer copy until the name decision is recorded.

## User Stories

1. As an invited indie genre author, I want to understand that access is limited to the Founding Author Lab, so that I know this is a controlled pilot rather than a public launch.
2. As an invited author, I want to know that the product sells credits rather than a guaranteed number of pages, so that I can make an informed purchase.
3. As an invited author, I want to see that a Starter pack costs $12 and contains 1,200 non-expiring credits, so that I understand the commercial contract before spending money.
4. As an invited author, I want to see an example of a 6–12-page reader magnet without being promised that result, so that the example helps me decide without misleading me.
5. As an invited author, I want additional Starter packs to remain available, so that I can continue experimenting after using my first 1,200 credits.
6. As an invited author, I want generation estimates and credit requirements shown before paid work begins, so that I can choose whether to proceed.
7. As an invited author, I want to know that output length, quality, continuity, and completion depend on usage and revisions, so that I do not mistake an illustrative workflow for a guarantee.
8. As an invited author, I want to attest that I own or control the rights to submitted material, so that my responsibilities are clear before upload.
9. As an invited author, I want the pilot to state that third-party generative models are used, so that I can decide whether the workflow fits my AI posture.
10. As an invited author, I want English to be the supported pilot language, so that I know what support and quality expectations apply.
11. As an invited author using another target language, I want that use clearly labeled unsupported rather than silently misrepresented, so that I can decide whether to proceed.
12. As a prospective author, I want a manual fit check before invitation, so that the pilot admits authors with a finished manuscript, clear rights, and realistic expectations.
13. As a pilot operator, I want invitations to reserve capacity in waves of two, so that I never over-admit the ten-customer cohort.
14. As a pilot operator, I want an unaccepted invitation to release its slot, so that an unavailable prospect does not permanently consume capacity.
15. As a pilot operator, I want the ten-customer limit to count successful paying customers, so that unpaid invitations do not distort cohort totals.
16. As a pilot operator, I want every member to have an offer version recorded, so that later changes cannot silently rewrite an existing purchase.
17. As a pilot operator, I want future purchases to use the currently published offer version, so that changes are explicit and traceable.
18. As a pilot operator, I want one canonical support mailbox and one separate legal mailbox, so that customer questions and legal/DMCA notices are routed correctly.
19. As a pilot author, I want support expectations stated as one-business-day acknowledgement and four-business-hour response for generation blockers, so that I know when to expect human attention.
20. As a pilot operator, I want the coverage window defined as weekdays from 09:00 to 17:00 Eastern Time excluding Ontario public holidays, so that response targets are measurable.
21. As a pilot author, I want to know that the pilot has one operator and may pause admissions or work when that operator is unavailable, so that the service promise is honest.
22. As a pilot operator, I want credits to be non-refundable by default, so that billing policy matches the existing terms and ledger model.
23. As a pilot operator, I want legally required or approved exception refunds to be documented and idempotent, so that Stripe money and spendable credits cannot diverge silently.
24. As a pilot author, I want operational metrics to be separated from marketing and case-study permission, so that using the pilot does not imply permission to promote my work.
25. As a pilot author, I want marketing and case-study permission to be off by default and requested after use, so that consent is informed and voluntary.
26. As a pilot operator, I want support notes to contain operational metadata but not manuscript text or sensitive creative content, so that support does not create an unnecessary data-retention risk.
27. As a pilot operator, I want provider spend reviewed after each customer project and weekly during active enrollment, so that unexplained cost variance is caught before the next wave.
28. As a pilot operator, I want a non-sensitive name decision record with a private practitioner pointer, so that the repository shows the current brand posture without exposing privileged advice.

## Implementation Decisions

- The first commercial audience is invited, AI-open indie genre authors with a finished manuscript or eligible source and a clear rights posture.
- Name clearance is a hard gate for customer-facing pilot activity. Engineering and internal testing may proceed behind explicit pilot gates while clearance is pending.
- The name review covers the United States and Canada plus a practical international conflict screen based on invited-author locations. A written practitioner recommendation must support limited pilot use or trigger a rename decision before customer-facing activation.
- The repository stores only jurisdictions, review date, outcome, permitted constraints, and a pointer to private practitioner material. Privileged advice is not committed.
- The offer is a repeatable $12 Starter purchase for 1,200 non-expiring credits. Package price and quantity remain server-sourced; the UI must not duplicate pricing constants.
- Additional purchases use the same Starter contract. The system does not model a reader magnet, page quota, or completion guarantee.
- The offer language may describe a 6–12-page reader magnet or first-chapter issue only as an illustrative use case. It must disclose that output length, quality, continuity, and completion vary with source material, provider use, and revisions.
- The pilot requires a rights attestation covering ownership or control of necessary rights and responsibility for submitted content. Scenewright does not verify rights or provide legal advice through the attestation.
- English is the supported pilot contract. Other target languages remain technically possible only where the product permits them and are labeled unsupported for pilot support and quality expectations.
- Admission is manual. The checklist covers author fit, source readiness, rights attestation, willingness to use third-party generative models, and English support expectations.
- Invitations reserve capacity in waves of two. A reserved slot is released when an invitation expires or is withdrawn; the ten-customer cohort count is based on successful first purchases.
- Each pilot membership and purchase records the accepted offer version. Existing purchases retain their terms; future purchases use the current published version.
- Public signup and public generation access remain disabled for the pilot. Authenticated users require active pilot membership for project creation, generation, regeneration, and export.
- The remote sample library/import surface is disabled for the pilot.
- `hello@scenewright.ink` is the canonical customer-support address; `support@scenewright.ink` aliases it; `legal@scenewright.ink` is separate and monitored for legal, abuse, and DMCA notices.
- Published support coverage is Monday–Friday, 09:00–17:00 Eastern Time, excluding Ontario public holidays. The target is acknowledgement within one business day and response to generation-blocking failures within four business hours during coverage.
- The pilot has one operator with no backup. This is an explicit accepted constraint. Admissions and generation commitments pause when the operator is unavailable; no redundancy claim is made.
- Credits are non-refundable except where legally required or where the operator approves a documented exception. Exception refunds must reconcile Stripe and the credit ledger, preserve recovery state on partial failure, and be idempotent.
- Operational metrics are distinct from optional marketing and case-study permission. Marketing and case-study permission is explicit, separate, and off by default.
- Operator notes contain only operational metadata such as identifiers, support history, incident references, cost/recovery notes, and consent timestamps. Manuscript text, generated images, and sensitive creative content are not copied into those notes.
- Provider spend is reviewed after every customer project and at least weekly while the cohort is active; unexplained variance blocks the next admission wave until investigated.

## Testing Decisions

- Tests verify external behavior at the API/UI boundary: pilot membership authorization, invitation state, capacity reservation/release, server-sourced Starter pricing, credit balances, rights/support disclosures, language labeling, offer-version persistence, and disabled sample-library access.
- Billing tests cover repeated Starter purchases, exactly-once crediting, unknown or duplicate refund requests, partially used grants, unused approved refunds, and recoverable Stripe/local-write divergence.
- Operations tests verify the published mailbox and support-policy values, single-operator pause behavior, data-minimized operator notes, and provider cost-review evidence.
- Name-clearance tests verify the decision record shape and gate behavior, not the practitioner’s legal conclusion.
- Existing high-level router, billing, credit-estimate, frontend page, and launch-safety tests are the prior art. New tests should follow their externally observable style and avoid asserting internal implementation structure.
- Deployed acceptance must verify that public signup is disabled, an admin-invited member can confirm/sign in/reset a password, a non-member is denied generation work, a member sees the current Starter contract, and a real internal purchase/refund rehearsal reconciles Stripe and the ledger.

## Out of Scope

- Public signup, public acquisition, paid advertising, broad promotion, a free tier, referral loops, or a zero-touch launch.
- A guaranteed reader magnet, page-count entitlement, continuity guarantee, copyright-protection guarantee, or KDP-acceptance promise.
- A reader-magnet domain model, workflow quota, or special completion state.
- Automatic genre classification, automatic rights verification, or legal advice.
- A backup operator or redundant support organization.
- Non-English support commitments for the first cohort.
- Privileged legal advice or a full trademark search memo in the repository.
- Implementation of later readiness slices such as release identity, security headers, input bounds, monitoring, backups, learning instrumentation, or real-provider proof production, except where Slice 0 requires their policy inputs.

## Further Notes

- This spec records the decisions reached while grilling Slice 0 of the proposed pre-offer readiness plan. The implementation plan remains the dependency map for later slices.
- The single-operator decision is intentionally visible as operational risk; it should be revisited before expanding beyond the ten-customer cohort.
- The name decision should be completed before customer outreach, paid transactions, public promotion, or activation of customer-facing offer copy.


