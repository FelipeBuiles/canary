#!/usr/bin/env python3
"""Create launch views in the configured PostHog project; reruns reuse named views.

Requires POSTHOG_API_KEY (personal management key), POSTHOG_PROJECT_ID, and
POSTHOG_HOST. Ingestion tokens cannot create dashboards. No customer data sent.
"""
import json
import os
from urllib.request import Request, urlopen


def request(path, body=None):
    host = {"https://us.i.posthog.com": "https://us.posthog.com",
            "https://eu.i.posthog.com": "https://eu.posthog.com"}[os.environ["POSTHOG_HOST"].rstrip("/")]
    token = os.environ["POSTHOG_API_KEY"]
    project = int(os.environ["POSTHOG_PROJECT_ID"])
    req = Request(f"{host}/api/projects/{project}/{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urlopen(req, timeout=20) as response:
        return json.load(response)


def definitions():
    events = ["project_created", "stage_approved", "style_selected", "page_ready", "export_package_ready"]
    return [
        {"name": "Canary launch: author milestones", "description": "Distinct accounts; filter environment=production. Counts are not ordered conversion rates.",
         "query": {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", "version": 2,
            "series": [{"kind": "EventsNode", "event": e, "name": e, "math": "dau"} for e in events],
            "dateRange": {"date_from": "-30d"}, "trendsFilter": {},
            "properties": [{"key": "environment", "value": ["production"], "operator": "exact", "type": "event"}]}}},
        {"name": "Canary launch: first output funnel", "description": "Ordered account funnel, 7 days. An account can use multiple projects; use the first-project cohort for activation decisions. Recent starters are still in window.",
         "query": {"kind": "InsightVizNode", "source": {"kind": "FunnelsQuery",
            "series": [{"kind": "EventsNode", "event": e, "name": e} for e in ["project_created", "page_ready", "export_package_ready"]],
            "dateRange": {"date_from": "-30d"},
            "properties": [{"key": "environment", "value": ["production"], "operator": "exact", "type": "event"}],
            "funnelsFilter": {"funnelOrderType": "ordered", "funnelVizType": "steps", "funnelWindowInterval": 7, "funnelWindowIntervalUnit": "day"}}}},
        {"name": "Canary launch: friction and feedback", "description": "Failures, credit blocks, and feedback submissions. Read comments in Canary's private inbox.",
         "query": {"kind": "InsightVizNode", "source": {"kind": "TrendsQuery", "version": 2,
            "series": [{"kind": "EventsNode", "event": e, "name": e, "math": "total"} for e in ["stage_failed", "credit_blocked", "feedback_submitted"]],
            "dateRange": {"date_from": "-30d"}, "trendsFilter": {},
            "properties": [{"key": "environment", "value": ["production"], "operator": "exact", "type": "event"}]}}},
    ]


def diagnostic_definitions():
    """Keep development visible without mixing it into production funnels."""
    queries = [
        ("Canary diagnostics: cost confidence",
         "Last 7 days, separated by environment and funding. Canary-reported and estimated costs only; unknown totals stay blank. PostHog's built-in AI total may infer catalog prices and is not billed spend.",
         """SELECT
    properties.environment AS environment,
    properties.funding AS funding,
    properties.cost_status AS cost_status,
    count() AS calls,
    sum(CASE WHEN properties.cost_status = 'reported' THEN toFloat(properties.cost_usd) ELSE NULL END) AS reported_usd,
    sum(CASE WHEN properties.cost_status = 'estimated' THEN toFloat(properties.cost_usd) ELSE NULL END) AS estimated_usd,
    countIf(properties.cost_status = 'unknown' OR properties.cost_status IS NULL) AS unknown_cost_calls
FROM events
WHERE event = '$ai_generation' AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY environment, funding, cost_status
ORDER BY environment, funding, cost_status"""),
        ("Canary diagnostics: AI outcomes by feature",
         "Last 7 days. Call outcomes, not page outcomes: draw.page_ocr failures are separate from complete_page_draw image failures. Split by environment, feature, model, and error type.",
         """SELECT
    properties.environment AS environment,
    properties.feature AS feature,
    properties.model_alias AS model,
    properties.status AS status,
    properties.error_type AS error_type,
    count() AS calls,
    avg(properties.latency_ms) AS average_latency_ms
FROM events
WHERE event = '$ai_generation' AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY environment, feature, model, status, error_type
ORDER BY environment, feature, calls DESC"""),
    ]
    return [{"name": name, "description": description,
             "query": {"kind": "DataVisualizationNode", "display": "ActionsTable",
                       "source": {"kind": "HogQLQuery", "query": query}}}
            for name, description, query in queries]


def main():
    name = "Canary launch learning"
    dashboards = request("dashboards/?limit=100")["results"]
    dashboard = next((item for item in dashboards if item["name"] == name), None)
    if dashboard is None:
        dashboard = request("dashboards/", {"name": name, "description": "Launch learning. Review weekly with first-party outcomes and private feedback.", "tags": ["canary-launch"]})
    existing = request("insights/?limit=100&dashboard=" + str(dashboard["id"]))["results"]
    for insight in definitions() + diagnostic_definitions():
        if not any(item.get("name") == insight["name"] for item in existing):
            request("insights/", {**insight, "dashboards": [dashboard["id"]], "tags": ["canary-launch"]})
    print(f"Launch dashboard ready: {dashboard['id']}")


if __name__ == "__main__":
    main()
