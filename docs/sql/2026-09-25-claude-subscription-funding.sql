-- Record local Claude Code subscription calls in ai_usage_events.
-- Subscription usage never settles credits, so credit_ledger.funding and
-- settle_model_usage keep rejecting 'claude_subscription' (fail closed).
-- Apply as an administrator before deploying the matching application binary.
BEGIN;
ALTER TABLE public.ai_usage_events
  DROP CONSTRAINT IF EXISTS ai_usage_events_funding_check;
ALTER TABLE public.ai_usage_events
  ADD CONSTRAINT ai_usage_events_funding_check
  CHECK (funding in ('api', 'codex_subscription', 'claude_subscription'));

-- Subscription rows have no monetary cost; keep NULL rather than coalescing to 0.
create or replace view public.ops_ai_cost_daily
with (security_invoker = true) as
select
  date_trunc('day', created_at) as day,
  stage,
  feature,
  provider,
  coalesce(provider_model, model_alias) as model,
  operation,
  status,
  billable,
  count(*)::bigint as call_count,
  coalesce(sum(input_tokens), 0)::bigint as input_tokens,
  coalesce(sum(output_tokens), 0)::bigint as output_tokens,
  coalesce(sum(image_count), 0)::bigint as image_count,
  (case when funding in ('codex_subscription', 'claude_subscription') then sum(cost_usd)
    else coalesce(sum(cost_usd), 0) end)::numeric(14, 6) as actual_cost_usd,
  coalesce(sum(estimated_cost_usd), 0)::numeric(14, 6) as estimated_cost_usd,
  percentile_cont(0.5) within group (order by latency_ms)
    filter (where latency_ms is not null) as latency_p50_ms,
  percentile_cont(0.95) within group (order by latency_ms)
    filter (where latency_ms is not null) as latency_p95_ms,
  funding,
  count(*) filter (where cost_usd is null)::bigint as unknown_cost_count
from public.ai_usage_events
group by 1, 2, 3, 4, 5, 6, 7, 8, funding;
COMMIT;
