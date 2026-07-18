# Pricing Cache & Cost Calculation — Review and Implementation Plan

**Date:** 2026-05-08
**Scope:** `novel_to_comic/src/novel_to_comic/model_costs.py`,
`novel_to_comic/src/novel_to_comic/usage.py`,
`novel_to_comic/src/novel_to_comic/server/credits.py`,
`novel_to_comic/src/novel_to_comic/litellm_model_prices.cached.json`,
`novel_to_comic/src/novel_to_comic/litellm_pricing_overrides.yaml`.

**Status:** Findings documented; implementation pending.

---

## 1. Summary

The runtime billing path (LiteLLM proxy returns a `response_cost` header) is
sound — the proxy is the source of truth for actual provider charges. But three
non-runtime paths depend on hand-curated price tables that are not refreshed,
not audited, not version-stamped on the credit ledger, and contain entries that
were extrapolated rather than verified. Those paths are:

1. Pre-flight reservation estimates (every stage start)
2. Failed-request billing (when `ai_bill_failed_requests=estimate_all`)
3. Image-edit endpoints that don't reliably return a cost header

This doc captures the seven concrete issues found and a priority-ordered plan
to fix them.

---

## 2. Background — How pricing flows today

```
UsageRecord (one API call)
   └─ calculate_cost_breakdown            (usage.py:50)
        └─ PricingResolver.calculate      (model_costs.py:99)
             1. If cost_usd from LiteLLM response header → USE IT, stop.
             2. Resolve alias → provider model via overrides.aliases
             3. Look up provider model in cached cost map
             4. Else look up in overrides.model_overrides
             5. Else return $0.00 + source="unknown_pricing"
```

Three data sources:

| File | Role |
|---|---|
| `litellm_model_prices.cached.json` | Misnamed "cache" — actually a hand-curated 17-entry pinned snapshot |
| `litellm_pricing_overrides.yaml` | Alias→provider map, image token tables, fallback prices for models missing upstream |
| LiteLLM proxy response header `x-litellm-response-cost` | Authoritative for settled charges |

---

## 3. Findings

### F1. The "cached" file is not actually a cache from upstream
**File:** `litellm_model_prices.cached.json`
**Severity:** High

The file's own header reads:
> "Minimal pinned fallback for Canary's configured models. Refresh with the
> full LiteLLM cost map when network access is available."

It contains 17 hand-entered model rows dated 2026-04-30, not the ~5000-entry
upstream `model_prices_and_context_window.json`. The filename `*.cached.json`
implies derived/refreshable content but nothing refreshes it.

### F2. `refresh_litellm_cost_cache` is dead code
**File:** `model_costs.py:263`
**Severity:** High

The function exists, fetches the upstream JSON, and writes it to disk. But:
```
$ grep -rn "refresh_litellm_cost_cache" --include="*.py" --include="*.ts" \
    --include="*.md" --include="*.sh" --include="*.yaml"
model_costs.py:263:def refresh_litellm_cost_cache(
# (only the definition — no callers anywhere)
```
No CLI command, no startup hook, no cron, no test, no docs reference.

### F3. Several override prices were extrapolated, not verified
**File:** `litellm_pricing_overrides.yaml`
**Severity:** High

In the alias rename (commit landing 2026-05-08), prices were added by
extrapolating from sibling models without checking provider docs:

| Model | Added in/out per token | Status |
|---|---|---|
| `claude-haiku-4-5` | $1 / $5 per Mtok | UNVERIFIED |
| `claude-opus-4-7` | $15 / $75 per Mtok | UNVERIFIED |
| `gpt-5.4` | $2.5 / $15 per Mtok | UNVERIFIED |
| `gemini-3.1-flash-preview` | $0.30 / $2.5 per Mtok | UNVERIFIED |

These are plausible but were never cross-checked against an actual
Anthropic/OpenAI/Vertex pricing page or a real invoice.

### F4. Pricing snapshot is incomplete and never persisted
**Files:** `model_costs.py:64-69`, `server/credits.py:429-449`
**Severity:** Medium

`PricingResolver._snapshot_id()` hashes only the cache file, not the overrides
yaml. So editing override prices doesn't bump the snapshot. Even worse,
`pricing_snapshot` is attached to every `CostBreakdown` but **never written to
`credit_ledger`** in `debit_model_usage()`. There's no column for it, so
historical charges can't be reconstructed against the price table that produced
them.

### F5. `audit_pricing()` exists but no caller
**File:** `usage.py:164-201`
**Severity:** Medium

Function returns the list of configured models that are missing pricing
entries. Could detect drift after every alias change. Currently unreferenced
in tests, server startup, or CI.

This is more important now that the gateway has 15 intent×preset aliases —
adding/removing aliases without updating overrides is silently lossy.

### F6. gpt-image-2 token tables are guesses copied from gpt-image-1
**File:** `litellm_pricing_overrides.yaml:34-40`
**Severity:** Low-Medium

The override yaml admits it:
> "Sources for the gpt-image-2 numbers below: OpenAI's published gpt-image-1
> token figures (square 1024x1024) — gpt-image-2 reuses the same accounting.
> Re-tune these after sampling actual usage rows if estimates drift."

There's no observability hook surfacing estimate-vs-actual drift, so the
re-tuning never happens.

### F7. Configured models don't exist in upstream LiteLLM
**File:** `litellm_pricing_overrides.yaml:51-78`, `litellm/config.yaml`
**Severity:** Informational (changes refresh strategy)

`gemini-3.1-*-preview`, `claude-sonnet-4-6`, `claude-haiku-4-5`,
`claude-opus-4-7`, `gpt-5.4*` are not in BerriAI's public
`model_prices_and_context_window.json`. The override yaml is the **only**
pricing source for these. A successful refresh from upstream wouldn't help
these specific models — refresh primarily benefits widely-known stable models.

This means the override yaml is load-bearing and must be treated as a
first-class production config, not a fallback.

---

## 4. Implementation Plan

Tasks are ordered by impact-on-billing-correctness × ease. Each task is
self-contained — pick up any block without needing the others.

### T1. Verify and correct the four extrapolated prices  (F3)
**Effort:** 30 min  •  **Blocks:** nothing

For each model below, fetch the actual provider page and update
`litellm_pricing_overrides.yaml` if values differ:

- `claude-haiku-4-5` — Anthropic pricing page
- `claude-opus-4-7` — Anthropic pricing page
- `gpt-5.4` — OpenAI pricing page (verify both base and `-mini` variant)
- `gemini-3.1-flash-preview` — Vertex AI / Gemini API pricing
- Also re-verify cached entries: `gemini-3.1-pro-preview`,
  `gemini-3.1-flash-lite-preview`, `claude-sonnet-4-6`, `gpt-5.4-mini`,
  `gpt-image-2`. These were entered manually on 2026-04-30.

Acceptance: every override price has a comment citing the source URL and the
date last verified.

### T2. Refresh-on-startup with TTL  (F1, F2)
**Effort:** 1-2 hours  •  **Blocks:** nothing

Add a startup hook that calls `refresh_litellm_cost_cache()` on server boot if
the on-disk file is older than `PULP_PRICING_REFRESH_DAYS` (default: 7).

Implementation sketch:

```python
# novel_to_comic/server/app.py (or wherever app startup lives)
from novel_to_comic.model_costs import (
    DEFAULT_COST_MAP_PATH,
    refresh_litellm_cost_cache,
)

def _maybe_refresh_pricing() -> None:
    ttl_days = int(os.environ.get("PULP_PRICING_REFRESH_DAYS", "7"))
    try:
        age_seconds = time.time() - DEFAULT_COST_MAP_PATH.stat().st_mtime
    except FileNotFoundError:
        age_seconds = float("inf")
    if age_seconds < ttl_days * 86400:
        return
    try:
        meta = refresh_litellm_cost_cache(timeout_seconds=10)
        logger.info("Refreshed LiteLLM cost cache: %s", meta)
    except Exception as exc:
        logger.warning(
            "LiteLLM cost cache refresh failed; using on-disk file: %s", exc
        )

# Wire into FastAPI lifespan startup.
```

Constraints:
- **Never block startup on the network call.** If it fails or times out, log
  and continue with whatever's on disk.
- **Never refetch on the request hot path.** All caller mtime checks happen
  at startup only.
- Document the env var in `.env.example` and `docs/reference/config-fields.md`.

Acceptance:
- Server logs show one of `Refreshed LiteLLM cost cache: …` or
  `LiteLLM cost cache refresh failed; using on-disk file: …` on every boot
  past the TTL.
- The file's `_canary_cache.snapshot` field gets overwritten with upstream
  content (no longer says "canary-minimal-2026-04-30").
- Stop/start with a fresh on-disk file shows successful fetch.

### T3. Rename `*.cached.json` → `*.pinned.json` (or remove the misnomer)  (F1)
**Effort:** 15 min  •  **Blocks:** nothing (do AFTER T2 if you keep the cache)

Once T2 is in place, the file genuinely IS a cache and the name is honest.
If T2 is not adopted, rename to `litellm_model_prices.pinned.json` and update
`DEFAULT_COST_MAP_PATH` in `model_costs.py:20`.

### T4. Run `audit_pricing()` at startup, fail loudly  (F5)
**Effort:** 30 min  •  **Blocks:** T1 (so audits don't trip on prices we're
about to fix)

Wire `audit_pricing()` into server startup. Treat missing pricing as a
deployment error in production:

```python
def _audit_pricing_at_startup() -> None:
    missing = audit_pricing()
    if not missing:
        return
    msg = f"Pricing entries missing for: {missing}"
    if os.environ.get("ENV", "dev") == "production":
        raise RuntimeError(msg)
    logger.warning(msg)
```

Also update `audit_pricing()` itself ([usage.py:175-188](../../../novel_to_comic/src/novel_to_comic/usage.py)) to enumerate all
15 gateway aliases (`extract-fast` … `image-quality`) instead of just
`MODEL_REGISTRY` keys + image defaults. Use the values in
`config._QUALITY_PRESETS` as the source of truth.

Acceptance:
- Removing one entry from `litellm_pricing_overrides.yaml` and starting the
  server fails (production) or warns (dev).
- Adding a new alias to `litellm/config.yaml` without updating the override
  yaml gets caught at boot.

### T5. Persist `pricing_snapshot` to `credit_ledger`  (F4)
**Effort:** 1-2 hours  •  **Blocks:** schema migration coordination

Two parts:

a. Fix the snapshot to include both files:
```python
# model_costs.py
def _snapshot_id(self) -> str:
    h = hashlib.sha256()
    for path in (self.cost_map_path, self.overrides_path):
        try:
            h.update(path.read_bytes())
        except Exception:
            h.update(b"<unavailable>")
    return f"{self.cost_map_path.name}+overrides:{h.hexdigest()[:12]}"
```

b. Add a `pricing_snapshot text` column to `credit_ledger` and write it in
`debit_model_usage()`:
```python
# server/credits.py:429
db.table("credit_ledger").upsert({
    ...,
    "pricing_snapshot": cost.pricing_snapshot if cost else None,
}, on_conflict="usage_call_id").execute()
```

Migration must be deployed before the code change to avoid insert failures.

Acceptance: settled credit_ledger rows contain a `pricing_snapshot` value;
auditors can grep for snapshot IDs and re-derive prices for any historical
charge.

### T6. Estimate-vs-actual drift telemetry for image models  (F6)
**Effort:** 2-3 hours  •  **Blocks:** nothing; can ship after T1

Add a Langfuse / log event whenever:
1. We made a pre-call image cost estimate (reservation), AND
2. We have a settled provider cost from LiteLLM for the same call

Compute `(actual - estimated) / estimated`. Emit as a metric. Surface in a
weekly digest if the median drift exceeds ±20% across enough samples.

Implementation hook: `debit_model_usage` already has both numbers in scope
(`usage` carries actual cost, the reservation row carries the estimate).

Acceptance: a Langfuse metric `pricing_estimate_drift_pct` tagged by model
alias is queryable over the last 7 days.

### T7. Smoke test: typical-project cost estimate  (F3, F5)
**Effort:** 30 min  •  **Blocks:** nothing

Add a pytest case that runs `estimate_stage_credit_breakdown` against a fixed
synthetic project (cached `story_bible.json`, fixed novel size) for each of
the three quality presets. Assert the estimate falls in a hand-set range:

```python
def test_balanced_extract_estimate_in_sane_range(tmp_path):
    state = _make_test_state(tmp_path, novel_size_kb=120)
    config = Config(quality_preset="balanced")
    estimate = estimate_stage_credit_breakdown(config, tmp_path, state, "extract")
    # If this trips, either model pricing changed materially or the estimate
    # logic regressed. Both are worth a human checking.
    assert 50 <= estimate["estimate_credits"] <= 500
```

Goal isn't tight bounds — it's catching ×10 regressions if someone mistypes
a price (e.g. enters `$0.0003` instead of `$0.00003`).

Acceptance: CI fails if any preset's typical estimate moves outside the
asserted range.

---

## 5. Out of scope for this plan

- Per-customer pricing tiers / negotiated rates
- Multi-currency support
- Caching the upstream LiteLLM file in S3 / Supabase Storage instead of a
  bundled JSON (overkill for current scale)
- Real-time price changes within a session — refreshes are TTL-based by design

---

## 6. Verification checklist (after all tasks land)

- [ ] T1: every override price in `litellm_pricing_overrides.yaml` has a
      `# source: <url>, verified <date>` comment.
- [ ] T2: server logs include refresh attempt on every boot past the TTL;
      manual `touch -t 197001010000` on the cache file forces a refresh next
      boot.
- [ ] T3: file rename complete; `grep -r 'cached.json' src/` only matches the
      expected one path (or `pinned.json` if T2 not adopted).
- [ ] T4: removing any line from `aliases:` block of overrides yaml fails
      production boot.
- [ ] T5: latest 10 settled rows in `credit_ledger` have a non-null
      `pricing_snapshot`.
- [ ] T6: Langfuse dashboard shows `pricing_estimate_drift_pct` for at least
      one image model.
- [ ] T7: introducing an off-by-10x price typo in the override yaml causes
      `pytest tests/test_pricing_smoke.py` to fail.

---

## 7. References

- `model_costs.py` — `PricingResolver`, `refresh_litellm_cost_cache`
- `usage.py` — `calculate_cost`, `estimate_text_cost`, `estimate_image_cost`,
  `audit_pricing`
- `server/credits.py` — `usage_to_credit_debit`,
  `estimate_stage_credit_breakdown`, `debit_model_usage`
- LiteLLM upstream cost map:
  `https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json`
- Related: `2026-04-29-ai-gateway-litellm-design.md` (the gateway migration
  this pricing layer was built for)
