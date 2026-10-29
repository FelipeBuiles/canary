# Competitor gaps, 2026-10-27

Run for the first marketing plan. Skill: `competitor-intel`. Snapshot only, not a trend.

## Scope and usage

- Caps for this run: 3 competitors (operator bound), 8 search queries, 4 pages per competitor, 30 external calls.
- Used: 3 search queries (shared with discovery), 6 page fetches (LlamaGen 2, Narrora 2, Novel2Comic 2), no failures.
- Stop reason: competitor cap reached.
- Canary synced at lock `83b9d06a` before research (`npm run sync:canary`, unchanged).

## Profiles

- `intel/competitors/llamagen.md`
- `intel/competitors/narrora.md`
- `intel/competitors/novel2comic.md`

Other candidates seen only in search results and not profiled: BubbleStory, GenToon, Storieta, ComicInk, Comicory, StoryComic AI. Storieta's search snippet said "Your first chapter is free". It was not fetched, so treat it as a lead only.

## Scenewright baseline (marketable ledger ids)

- Turns a novel into a comic (`what-it-is`), for writers without an art team (`audience`).
- Guided pipeline, not an image canvas (`guided-pipeline`).
- EPUB, PDF or TXT in, PDF or CBZ out, no subscription (`input-formats-public`, `export-pdf-cbz`).
- One-time packs from US$12, credits never expire (`pack-starter`, `no-subscription-credits-never-expire`).
- Continuity is helped by references, never promised (`step-cast`, `continuity-not-guaranteed`).
- Integrated or editable lettering (`lettering-choice`).
- Missing from the ledger: any measured output quality, page counts per pack, or turnaround time.

## Gaps (at most three)

1. **A free first try.** Buyer task: "will this work on my book before I pay?" Evidence: Narrora offers a free account ("Create a free Narrora account — no credit card", narrora.com/novel-to-comic). Novel2Comic gives new accounts "some free credits" (novel2comic.com/en). Scenewright's side: `start-small` and the sample shelf (`sample-stories`), but no ledger fact for a free trial, and the claims policy bans advertising one. Limitation: competitors' free tiers have unknown size and cost. Next action: no public change. The owner decides on the canary proposal "free first style proof at sign-up" (growth strategy, Decision 5). This is a hypothesis, not a measured loss.
2. **Export formats and input breadth.** Scenewright publicly lists EPUB, PDF and TXT in and PDF or CBZ out (`input-formats-public`, `export-pdf-cbz`). Novel2Comic's FAQ asks for a "UTF-8 plain text (.txt) file". Formats were not seen on the LlamaGen or Narrora pages, so that is unknown, not missing. Next action: keep formats visible on owned pages. This is the clearest verified difference in the evidence.
3. **Honest continuity wording.** Narrora promises "Same face. Every panel. No drift." Scenewright's ledger says references reduce drift (`continuity-not-guaranteed`). Novel2Comic uses similarly honest wording. Hypothesis: AI-wary authors may trust the qualified claim more. Do not attack a named competitor in copy (claims policy). Next action: none this week.

No pricing advantage is claimed. Credits are different units in each product, and Novel2Comic's pack prices are unknown.
