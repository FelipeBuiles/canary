# Community scan, 2026-10-27

Skill: `community-scan`. One bounded pass for the first marketing plan. No opportunities were saved and no replies were drafted.

## Budget and stop reason

- Caps: 8 search queries (operator bound), 12 threads, 30 external calls, 3 consecutive access errors.
- Used: 8 search queries (2 search calls of 4 queries, recency filter "month"), then 1 fetch batch of 5 URLs.
- Stop reason: **5 consecutive access errors**, past the limit of 3:
  - 4 Reddit URLs, two threads and two rules pages: "Error - Could not extract readable content from HTML structure".
  - The Royal Road forum thread: "Error - HTTP 403: Forbidden".
- Existing community reply drafts in the workspace: 0.

## Queries run

1. reddit selfpublish turn my novel into a comic
2. reddit how to adapt my novel into a graphic novel
3. royal road forum comic adaptation of my web serial
4. reddit indie author comic excerpt reader magnet
5. reddit writer can't afford artist comic adaptation of my book
6. reddit selfpublish AI generated comic of my novel worth it
7. reddit royalroad AI art cover illustrations for my serial
8. reddit tool for turning a short story into comic pages

## Candidates (search leads only, unscored)

The skill requires opening the thread and the community's rules before scoring. Neither worked, so none of these has a `relevance` score or an opportunity file. Dates come from the search provider.

| Thread | Community | Posted | Why it surfaced | Blocker |
|---|---|---|---|---|
| https://www.reddit.com/r/ComicWriting/comments/1wtot9i/using_ai_to_create_a_draft/ | r/ComicWriting | 2026-09-29 | Writer wants AI drafts of a comic from their own story | Fetch failed. The top reply in the snippet is hostile to AI. Canary's tester kit does not list this community as AI-friendly |
| https://www.royalroad.com/forums/thread/177933 | Royal Road forums | 2026-10-02 | Serial author cannot afford art and asks about AI covers. Replies say AI covers are common on Royal Road | HTTP 403. About covers, not comics |
| https://www.reddit.com/r/writingadvice/comments/1wskk8y/order_of_operations_for_my_novelmanga/ | r/writingadvice | 2026-09-28 | Serial novelist planning a manga version | Fetch failed. The author already pays an artist |
| https://www.reddit.com/r/mangaideas/comments/1ws8uc8/looking_for_an_artist_to_turn_my_story_into_a/ | r/mangaideas | 2026-09-28 | "I can write, but I can't draw" | Not fetched (stopped). Looking for an artist partner |
| https://www.reddit.com/r/ComicBookCollabs/comments/1wsyk01/inquiring_dont_have_the_money_now_but_looking_to/ | r/ComicBookCollabs | 2026-09-29 | Writer pricing sample pages for crowdfunding | Not fetched. Canary's kit lists r/ComicBookCollabs as AI-banned |

## Demand signals worth keeping (leads, not evidence)

- Writers who "can't draw" and can't afford an artist keep appearing in comic and manga communities. Many of those communities ban AI.
- In the Royal Road thread, replies describe AI covers as widespread. That suggests the serial-author segment that canary's strategy ranks first is more AI-tolerant.
- Every lead was 25 to 30 days old. Search found nothing fresher.

## Next pass

Use a fetch path that can read Reddit (for example, a read-only browser) before the next scan. Start with the communities that canary's `docs/ops/tester-recruitment-2026-10.md` rates as AI-friendly (r/WritingWithAI, r/aicomicmakers, Royal Road author areas) and re-read each community's rules first.
