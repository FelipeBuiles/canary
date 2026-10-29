# Setup completion report

This report is for the agent reviewing the scenewright-marketing setup. It lists what was built, how each part was verified, who verified it, and what is still open. Read `.audit/setup.tsv` for the decision trail and `.audit/research/` for the two design-input reports.

## Scope the user agreed to

- An agent-first workspace with a thin local Vite + React review desk. No database.
- Ported ideas from Falbor: community demand capture, competitor intel, content and SEO/AEO, ads and creative.
- Canary (`../canary`) is a read-only sibling, synced by script.
- Drafts only. A human approves and posts everything. This repo does not own the public site.
- MCP sources: PostHog (project 630262) and Agentgrown (`https://agentgrown.com/mcp`).
- A private GitHub repo: https://github.com/FelipeBuiles/scenewright-marketing.

## What exists

**Domain and gate.** `src/domain.ts` defines zod schemas for drafts, competitors, opportunities, facts, the canary lock, and the manifest. Draft status is a discriminated union (draft, approved, published, rejected). Published is terminal. `src/audit.ts` is a pure function that checks fact quotes against cited canary lines, source attestations, manifest membership, duplicate ids, and draft references. `npm run check` runs `tsc`, Vitest, the community scorer verifier, and the audit, in that order.

**Approval integrity.** The approval hash covers kind, channel, target, title, facts, sources, created, and the trimmed body. The review API also requires a revision token that hashes the draft, the ledger, the audit issues, the lock, and the manifest. A browser holding an old view gets a 409 and writes nothing.

**Fact drift that survives sync.** Each fact has optional `verifiedSources`, mapping a cited canary file to the SHA-256 of the whole file at the time a person or agent reviewed the claim's meaning. Sync never writes this field. If a cited file changes, the ledger warns, and any draft citing that fact gets an error and cannot be approved until someone re-reviews the claim and renews the hash.

**Canary sync.** `scripts/sync-canary.ts` pins canary HEAD and hashes the 65 files named in `knowledge/canary-manifest.json`. It writes `knowledge/canary-changes.md` with commits and changed or removed files. An unchanged sync now writes nothing, so the lock and changelog stay byte-identical. Output paths are checked with `lstat`, so a dangling symlink cannot redirect a write outside the workspace.

**Review desk.** `ui/api.ts` is a Vite dev-server plugin. Writes need an exact `127.0.0.1` origin and host, `application/json`, and a body under 64 KiB. Malformed YAML or JSON becomes a diagnostic instead of a crash. Draft and canary symlinks are refused. `ui/src/App.tsx` shows a stale banner and disables actions when a refresh fails, offers retry on first-load failure, and moves to the draft's new tab after a transition.

**Knowledge.** `knowledge/facts.yaml` has 65 facts (45 marketable, 20 internal-only) with 81 source attestations across 24 canary files. `knowledge/claims-policy.md` lists banned claims, canary's internal contradictions, the copyright no-go list, and per-book creative restrictions.

**Skills** (`.agents/skills/`):

| Skill | Lines | Ported from Falbor |
| --- | --- | --- |
| `community-scan` | 85 | Reddit scoring prompt, six factors plus recency, draft rules (`app/lib/automation/prompts.ts`) |
| `competitor-intel` | 59 | Profile extraction and conflict analysis, minus Falbor's unsourced metrics |
| `ai-visibility` | 54 | Buyer-question probe and mention formulas. Returns BLOCKED without real engine responses |
| `content-seo` | 137 | Evidence-only query research, opportunity prompt, gap-targeted article prompt (`pages.ts:180-185`) |
| `ad-creative` | 152 | Composition constraints. Ad copy is new; Falbor never generated any |
| `growth-analytics` | 223 | None. Written fresh against canary's PostHog event schema |
| `product-facts` | 49 | None. Maintains the ledger and attestations |

Adapted files carry Falbor attribution. `THIRD_PARTY_NOTICES.md` and `third_party/falbor/NOTICE.md` record that Falbor defaults to AGPL-3.0 and excludes its trademarks.

**Sample output.** `drafts/blog/2026-10-27-start-with-one-chapter.md` is an evergreen article citing four marketable facts. Its claim map lives in `intel/reports/2026-10-27-start-with-one-chapter-claim-map.md`, because the desk's Copy text button copies the whole draft body.

## Verification

| Check | Result | Who ran it |
| --- | --- | --- |
| `npm run check` | exit 0. 4 test files, 26 tests, scorer verifier, audit 1 draft / 65 facts / 0 errors / 0 warnings | orchestrator, final tree |
| `npm run ui:build` | exit 0 | orchestrator, final tree |
| Real `npm run sync:canary` twice | Both runs report unchanged. Lock and changelog byte-identical | orchestrator, against real canary `83b9d06a` |
| Sync regression tests | 3 of 5 fail on the pre-fix logic; all pass on the fix | orchestrator, mutation check |
| Approval hash test | Dropping the body from the hash fails 3 tests | orchestrator, mutation check |
| Browser, desktop and 390px mobile | No horizontal overflow (body 390 of 390px) | orchestrator, `.audit/screenshots/desk-desktop.png`, `desk-mobile.png` |
| Browser, refresh failure | Stale banner shown, all actions disabled | orchestrator, `desk-stale.png` |
| Browser, first-load failure | Error plus a retry button | orchestrator, `desk-initial-error.png` |
| Browser, disk edit after load | Approve returns 409, file stays `draft`; after refresh, approve returns 200 | orchestrator, `desk-revision-conflict.png` |
| Browser, approve then back to draft | Desk follows the draft to Approved, then back to Draft. No page errors | orchestrator |
| Core security review | Two findings (dangling-symlink write, unchanged sync rewrite). Both fixed with tests | independent OpenAI reviewer |
| Skills and ledger review | One finding (an ad example allowed an undisclosed AI combination). Fixed, plus a test | independent OpenAI reviewer |
| Ledger audit with staged data | 0 issues. Kaitlin and Cthulhu asset hashes match the canary manifest | independent OpenAI reviewer |
| Comment audit | 3 narrating comments removed | comment-sicko agent |

## Open items

1. **MCP servers signed in on 2026-10-27.** `pi mcp list` shows PostHog connected (1 tool, `exec`) and Agentgrown connected (9 tools, including Search Console, GA4, and keyword volume). `content-seo` and `growth-analytics` now name those tools. Live queries were verified on 2026-10-27 from a headless `pi -p` session in this directory. Subagents launched from the orchestrator harness receive no MCP tools and report BLOCKED. Agentgrown bills about US$0.01 per call.
2. **The two sync fixes were not independently reviewed.** The OpenAI fixer hit its usage limit, so the orchestrator wrote the fix. A reviewer should read `scripts/sync-canary.ts` and `scripts/sync-canary.test.ts`.
3. **No workflow ran against the live web.** The sample article uses only local canary evidence. `community-scan`, `competitor-intel`, and `ai-visibility` have not run against real threads, competitor pages, or answer engines.
4. **Canary contradicts itself.** It says four stations in `PRODUCT.md` and five on the landing page. It accepts docx and md, but the landing page lists only EPUB, PDF, and TXT. Its copy kit bans prices, but the landing page shows them. The policy avoids all three in public copy until the product owner decides.
5. **Assets have only a paper clearance.** Asset hashes and rights records are checked. Nobody has visually reviewed a chosen page for ad placement.
6. **The fact audit can't check meaning.** It confirms each quote exists and its file hash matches. It can't confirm that free-form prose uses a fact correctly. Human review covers that.
7. **No performance comparison with Falbor.** Nobody measured Falbor's speed. The desk avoids a database and server-side model calls, but no speed claim has been measured.
8. **Approval hashes changed during setup.** Widening the hash invalidated any earlier approvals. No real approvals existed at that point.

## Known limits by design

The review API is a local dev server, not a deployed service. Symlink checks do not defend against a malicious local process racing the filesystem. The desk displays raw Markdown. Ad JSON and landing proposals need manual transfer into their editors.

## Addendum, 2026-10-27: marketing-plan

- New `marketing-plan` skill that runs the other skills and writes a beginner-readable weekly plan (`.agents/skills/marketing-plan/SKILL.md`).
- The desk has a read-only **Plans & reports** tab for `intel/reports/`. Unreadable or symlinked reports become non-blocking warnings (`ui/api.test.ts`).
- The manifest now watches `launch-readiness.md`, `self-service-launch.md`, `launch-scorecard-template.json`, and `routers/backoffice.py`.
- The first live plan is `intel/reports/2026-10-27-marketing-plan.md`. It used 8 PostHog calls and 6 Agentgrown calls (US$0.30). Its numbers come from those tool results and were not independently re-queried. A reviewer should spot-check the funnel counts in PostHog.
