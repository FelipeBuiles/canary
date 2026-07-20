# Canary operations assets

## Fly Grafana

After deploying the `[[metrics]]` configuration in `fly.toml`, open the Fly
metrics dashboard, choose **Dashboards → New → Import**, and import
`grafana/canary-application.json`. Select Fly's preconfigured Prometheus data
source when prompted.

The dashboard intentionally uses only aggregate custom metrics. Use Fly's
built-in dashboards beside it for Machine CPU, memory, filesystem/volume,
network, exits, and edge HTTP metrics.

Prometheus cost counters describe recent spend rate and reset with the process.
Use the Supabase `ops_ai_cost_daily`, `ops_usage_reconciliation`,
`ops_unit_economics_daily`, and `ops_product_funnel_daily` views for durable
cost, margin, reconciliation, and customer-funnel reporting.

## Production activation checklist

1. Apply `docs/supabase-schema.sql` in Supabase before deploying application
   code that writes product events or expanded purchase rows.
2. Deploy the updated `fly.toml`; confirm `/metrics` is scraped in Fly Grafana.
3. Configure backend and frontend Sentry DSNs. Start trace sampling at 5% and
   keep replay at zero until masking has been inspected with a test account.
4. Import the Grafana dashboard and verify every panel with a test stage run.
5. Run one Stripe test purchase and one paid model call, then confirm the
   operator views reconcile the purchase, provider cost, and credit debit.
