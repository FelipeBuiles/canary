-- Local change set; apply before enabling the GA4 browser integration.
-- A one-time browser attempt is optional evidence, separate from PostHog delivery.
begin;
alter table public.product_events add column if not exists ga4_signup_claimed_at timestamptz;
-- Exclude pre-rollout signups: enabling GA4 must not turn returning authors
-- into new conversions. New signup rows leave the marker null.
update public.product_events set ga4_signup_claimed_at = transaction_timestamp()
where event_name = 'account_created';
commit;
