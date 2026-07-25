# ADR 0015: Page-issue review by exception

**Status:** Accepted  
**Date:** 2026-07-25

## Decision

Generated pages are accepted by default and reviewed by exception. A user or
validator creates a page issue against a specific page-render revision. The
issue records evidence, the requested correction, and optionally a detected
panel region or canonical lettering item.

A region target localizes the problem but does not change the generation unit.
Draw resolves render-fidelity issues by producing a complete new page revision.
An issue requesting different wording returns to Adapt, after which Plan
creates a new ComicPage revision and Draw creates a new render. The issue
retains links to the superseded and corrected revisions so Finish can verify
the outcome.

The Pages station has one **Continue to Book** decision. It does not maintain
per-panel or per-page acceptance state. Unresolved page issues are summarized
before continuing; the user may correct them or deliberately accept them.
Invariant failures remain blocking and cannot be accepted through this path.

## Consequences

The target architecture removes panel acceptance records, panel flags,
per-panel regeneration state, panel-approval endpoints, and UI actions that
imply independently replaceable production panels.

Derived panel crops and detected regions remain useful for navigation and
issue localization. They do not acquire independent lifecycle or approval
state.
