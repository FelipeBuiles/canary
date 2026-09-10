# Style proofs — polish pass

The existing Living Ink system remains authoritative. The page is an artwork-led selection workspace: a compact dark introduction identifies the manuscript and selected direction; equal-size proof cards retain the complete images.

Selection and comparison controls follow the style title, before supporting prose. Story fit stays visible. Native disclosures expose the complete visual direction, palette, line rendering, lighting, sequential strengths, risks, and optional action audition. Both image types use contain sizing. The selected control remains high-contrast gold; selection progress and errors are explicit.

The comparison toolbar explains zero/one/two/three-proof states, names removable choices, and links to the comparison. Three choices are retained until the user removes one. Obsolete IDs from regenerated suggestions do not consume available slots. Existing selection, paid generation confirmations, estimates, recovery, and approval orchestration remain intact.

Verification: 344 frontend tests, production build, and lint pass. Manual detector returned no findings. Independent screenshot/code review: ship, no material findings. Desktop 1440 and mobile 390 captures use the actual components, app fonts, and existing project proof images in an isolated preview; authenticated shell and paid execution were not exercised. Temporary preview files and asset copies were removed.

Files: `web/src/pages/rooms/StyleRoom.tsx`, `web/src/components/style/StyleProofCard.tsx`, `web/src/__tests__/styleProofCard.test.tsx`, `web/src/__tests__/styleRoomComparison.test.tsx`.
