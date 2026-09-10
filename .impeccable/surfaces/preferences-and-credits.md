# Settings, Account, and Credits

Mode: Operate. Extend the incumbent Living Ink system with calm settings pages and a balance-led credit screen.

## Changes
- Shared settings layout: large readable title, one responsive navigation list, lighter panels and larger row copy. Project settings separates Language, Generation, Advanced, and Delete Project; current demo mode correctly displays Fast. Existing update and deletion handlers remain.
- Account: labelled email/password forms with autocomplete, true async error handling, and form state retained across tabs. Removed the unused current-password field and its misleading authorization claim; authenticated updateUser behavior remains.
- Credits: available balance, direct pack/history links, readable equal-weight pack cards, optional billing explanation, and larger ledger details. Existing prices, checkout IDs, charge/hold calculations, and refresh behavior remain. Load errors show unavailable values with read-only retry, plus checkout error/cancellation feedback.
- Removed unsupported pack popularity and obsolete fallback references to panel regeneration/Shot Plan.

## Verification
370 frontend tests across 66 files pass, including ten new tests for account submissions/draft retention and credit balances/packages/error/retry behavior. Production build and lint pass. Desktop and mobile screenshots inspected for all three screens; password view also inspected separately. Independent review found no actionable issues. Design detectors reported no findings.

Temporary browser fixtures used illustrative project and credit values; account preview had no signed-in user. No live account updates, checkout, deletion, or generation ran. Temporary fixture removed. Screenshots are in ../review/ (settings-*, account-*, credits-*). Existing DESIGN.md remains authoritative. The existing project settings route is /project/:id/settings; no new standalone /settings route was introduced.
