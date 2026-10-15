# Gemini prompt caching: handoff

Status: investigated 2026-10-13; recommendation is to close (see Follow-up findings). Not yet decided.

## Question

Canary re-sends large shared prompts: narrative reviews resend the whole story
context, repairs resend their original prompt, and Plan detail shards share
instructions and treatment. On Vertex Gemini, cached input costs a fraction of
normal input. In practice almost nothing is cached. Why, and is it worth fixing?

## Evidence so far

**Telemetry.** Until 2026-10-13 Canary ignored `prompt_tokens_details.cached_tokens`
on chat responses, so every call showed 0 cached tokens. That is fixed
(`novel_to_comic/src/novel_to_comic/ai/client.py`, the `prompt_cached` read).
Costs were always correct, since they come from the gateway.

**Production traffic (gateway spend logs, 30 days before 2026-10-13).**
- Gemini 3.8 Flash: 15 of 964 calls had cache hits, up to 32.6k cached tokens.
- Gemini 4 Argon: 0 of 76 calls. Vertex returned no cache field at all, including
  two review requests 8 seconds apart that shared a ~120k-token prefix.

**Probe (`work/argon-cache-probe*.py`, raw responses in `work/argon-cache-probe-20261013/`).**
- Explicit caching (`cachedContents`): Argon is rejected with a 400 ("does not
  support explicit context caching"). The same request works on Flash.
- Implicit caching works on Argon, direct and through the gateway, best-effort:
  - 6,765–7,421 of about 9k prompt tokens cached once warm.
  - A new prefix only started hitting after one or two earlier sends.
  - The last ~2,054 tokens were never cached.
  - Text appended inside the same message part missed; the same text sent as a
    separate part hit.

**Layout change made after the probe.**
- `ai/prompt_parts.CACHE_BREAK` splits a prompt into separate Gemini message
  parts; other providers get plain text. Used in `narrative_review.py` (stable
  story context first), repair and correction sites in `page_planning.py`,
  `book_adaptation.py` and `stages/s2_brief.py` (unchanged base prompt first).
- `gemini_tuning.tuned_request`: for models in `_CONTRACT_AFTER_CONTENT` (Argon)
  the output contract is the last user part; for Flash it was moved back into
  the system prompt after Flash Plan repairs rose, so Flash's system prompt
  differs per review window and shard (it carries per-window ID enums).

**After the layout change (Labs run `20261013-171728-bf5a8d`).** 3 of 226 calls
had any cached tokens.

## Hypotheses to test

1. **Too few sends per prefix.** The probe needed warm-up sends; a repair
   resends its base prompt once, and concurrent shards start together. If so,
   implicit caching can't help Canary's call pattern and the topic can close.
2. **The wire request differs from what Canary builds.** LiteLLM may merge
   parts, move the system instruction or add fields that change the prefix.
   Capture two sequential review requests at the gateway and diff the bytes
   Vertex receives.
3. **Endpoint or region spread.** Implicit cache entries may be scoped to a
   region or serving location; check which endpoint the gateway uses for Argon
   and Flash and whether consecutive calls land on the same one.
4. **Flash's system prompt.** With the contract in the system prompt, Flash
   prefixes diverge at the per-window enums before any shared story context.
   Explicit caching would also need a stable system prompt.

## Suggested next steps

1. Replay one real pair (a Plan review and its re-review after a repair) from
   local content traces through the gateway, sequentially, 3 times each, and
   record `cached_tokens`. Free of Canary orchestration; a few cents.
2. If hits appear only with warm-up, measure how many re-sends a real Plan run
   makes per prefix; that bounds the possible saving.
3. For Flash only, try explicit caching on the largest shared prefix (review
   story context) with a ~10 minute TTL; include storage cost in the comparison.
4. Decide with numbers. Earlier estimate: $0.20–0.40 per Argon Adapt+Plan run
   (10–15%). With the settled split (Argon Extract/Brief/Plan, Flash Adapt) the
   re-sent prefixes are mostly Plan reviews.

## Follow-up findings (2026-10-13, provider-free)

These come from the probe outputs, the LiteLLM source in the running
gateway, and PostHog content traces for Labs run `20261013-171728-bf5a8d`.
They cost nothing.

**The "separate part" result is confounded with warm-up.** LiteLLM's
`_gemini_convert_messages_with_history` merges consecutive user messages
into one Gemini `Content` with several parts. The probe's `parts_*` and
`messages_*` cases therefore sent the same request, and both report 9,475
prompt tokens. Across all probes, a new prefix missed on its first one or
two sends and then hit: `implicit_2`, `gateway_2`, `messages_q1` (third send)
and `r3`/`r4`/`r5`. `messages_q2` missed after a hit. `gateway_appended_tail`
was the only send of its request, so its miss fits warm-up as well as the
same-part explanation. The probes do not show that part boundaries matter.
`CACHE_BREAK` is harmless but unproven.

**The only Argon hit in the Labs run follows the same pattern.**
`extract.story_bible` got 7,077 of 9,131 tokens from cache at 17:44:16. That
was the fourth identical send, because every arm uses the same fixture. No
review, shard or repair call hit.

**Canary rarely re-sends a prefix in sequence.** Checked against the
captured inputs:

- *Plan reviews across phases.* The `plan_map` and `plan` reviews diverge at
  character 5,981: the first stable key is `"phase"` (`_STABLE_REVIEW_KEYS`
  in `narrative_review.py`). After it, the two reviews share only the
  treatment, about 21.6k escaped characters or roughly 5–6k tokens. Caching
  that would save about $0.01 per Argon run.
- *Detail shards.* Two shards diverge at character 168, because the first
  sentence names the target pages ("Expand only page-map entries 25-32").
  The JSON payload is also scoped to each shard (planning view, neighbouring
  map, entity inventory). Only the fixed instructions, a few thousand tokens,
  could be shared, and shards start at the same moment anyway.
- *Same-window resends* (repairs, protocol corrections, absence-claim
  confirmations) do repeat a prefix, but each base is sent only twice, and
  the probes hit on a second send only some of the time. The Argon arms in
  this run made zero Plan repairs and one review per phase.
- The two production reviews 8 seconds apart that shared about 120k tokens
  were most likely concurrent windows. An implicit cache entry cannot serve
  a request that starts before the first request has been processed.

**Upper bound.** The Argon full arm's Plan sent about 367k input tokens
(about $0.73 at $2/M). In a run without repairs, at most about 5–6k of those
tokens are re-sent in sequence. With repairs, each repaired shard or window
might save about $0.02 when its second send hits.

**Hypotheses 2–4.** No evidence that the gateway changes the prefix: the
system prompt goes to `systemInstruction` and user parts stay in order.
Both Argon and Flash use `VERTEXAI_LOCATION=global`. Global routing could
spread implicit-cache entries across regions, which would explain the
best-effort warm-up. Even so, there is little shared prefix to recover.
Flash's system prompt, which carries per-window enums, rules out
cross-window reuse on Flash. Under the settled split, Flash runs only Adapt.

**Recommendation: close the topic.** The limit is Canary's call pattern,
not the caching mechanism. Reaching meaningful savings would mean
restructuring prompts so that large stable content comes first in every
shard and phase, and staggering concurrent calls. That is a prompt-quality
and latency change, out of scope here, for at most cents per run. The paid
replay (next step 1) is not needed for this decision. Keep the
`cached_tokens` telemetry so a future call pattern (for example, long
multi-part books) can be checked cheaply.

## Out of scope

Prompt quality and the model split (settled; see `docs/reference/vertex-ai.md`).
Do not change the contract placement for Flash without a Plan repair-rate
comparison; it was reverted for that reason.
