# Cast — polish pass

The existing Living Ink visual system remains authoritative. The page introduces the manuscript’s cast with a compact dark header and category jump links. A labelled name search filters characters, places and props; no-match feedback and Clear search provide recovery. Stable keyed wrappers use hidden attributes instead of unmounting cards so expanded details and unsaved correction drafts survive filtering. Category links clear the search.

Character references use square frames and preserveAspectBox so the complete sheets remain visible. Location and prop previews also contain the complete image. Cards have readable headings, expandable verbatim visual anchors, and aligned, always-visible Review & adjust controls. The controls open existing modals; no paid operation is started by browsing. Existing regeneration, correction, job state, history, checkpoint consent and approval behavior is unchanged.

Appearance/reference thumbnails and history controls have larger labels and targets, wrapping names and visible keyboard focus. Missing references remain explicit and openable for deliberate generation.

Validation: production build, lint and 346 frontend tests pass. New search/review tests cover retained disclosures and unsaved correction text, cross-category searching, empty results, clearing, jump links and no mutations while browsing. Manual detector returned no findings. Independent desktop/mobile screenshot and code review: ship, no material issues. Captures use real components, application fonts and existing project artwork in an isolated local preview; authenticated shell and paid execution were not exercised. Temporary preview files and copied artwork were removed.

Implementation: web/src/pages/rooms/CastRoom.tsx. Tests: web/src/__tests__/castReferenceBrowser.test.tsx, plus existing cast recovery, consent and state-reference suites.
