# Adaptation and page plan reading views

Mode: Read. Writers explore the automatic adaptation and page plan to understand how their prose becomes comic pages.

## Direction

Full-width reading inside the Pages station replaces the narrow modal drawer. The incumbent Living Ink type, pulp background, red navigation, and Bristol page rows stay consistent. The document leads; navigation includes a return to the gallery, a document switch, and section or page anchors. Core beats remain visible; optional treatment and exact lettering use disclosures.

## Behavior

Existing reading query links remain valid, including sidebar links. Document navigation participates in browser history. Returning retains gallery filters and restores focus to its document button. The reader uses ordinary page scrolling without a modal focus trap. It is available independently of gallery loading. Plan entries follow the canonical plan order and show honest loading or unavailable states for missing detail records. No editing, approvals, or generation actions are introduced.

## Verification

355 frontend tests pass across 63 files. Tests cover document switching, deep links, return context, absence of paid calls, canonical plan ordering, partial detail states, optional treatment/lettering, and empty adaptations. Desktop and mobile renders inspected using a temporary illustrative story fixture. Section links were checked in the browser for focus and overflow. Design detector found no issues. Independent review identified three-digit sequence width, addressed with content-sized nonwrapping number columns. Temporary preview files removed. Existing global DESIGN.md remains authoritative.

Previews: adaptation-reader-desktop.png, adaptation-reader-mobile.png, page-plan-desktop.png and page-plan-mobile.png in ../review/. These are illustrative fixtures, not live project artifacts.
