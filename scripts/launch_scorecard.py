#!/usr/bin/env python3
"""Evaluate a manually reconciled launch packet; no network, spend, or mutations."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


GATES = (
    "release", "billing_isolation", "recovery_restore", "monitoring_support",
    "rights_name", "proof", "attribution",
)
COUNT_FIELDS = ("paid_starters", "exported_authors", "assisted_authors")
COST_FIELDS = (
    "support_minutes", "consumed_credit_revenue_usd", "provider_cost_usd",
    "payment_fees_usd", "consumed_credit_refunds_usd", "variable_infrastructure_usd",
    "support_cost_usd",
)


def evaluate(packet: dict) -> dict:
    """Missing, contradictory, or unknown evidence always holds acquisition."""
    holds: list[str] = []
    metrics: dict[str, float] = {}
    if packet.get("schema_version") != 1:
        holds.append("Use schema_version 1.")
    if packet.get("severe_incident_open") is not False:
        holds.append("Confirm that no severe billing, data, or privacy incident is open.")
    if not isinstance(packet.get("release_sha"), str) or not packet["release_sha"].strip():
        holds.append("Record the tested production release SHA.")
    gates = packet.get("gates", {})
    if not isinstance(gates, dict):
        gates = {}
    for name in GATES:
        gate = gates.get(name, {})
        if not isinstance(gate, dict) or gate.get("status") != "passed" or not isinstance(
            gate.get("evidence"), str
        ) or not gate["evidence"].strip():
            holds.append(f"{name}: passing evidence is missing.")

    cohort = packet.get("cohort", {})
    if not isinstance(cohort, dict):
        cohort = {}
    if cohort.get("seven_day_window_closed") is not True:
        holds.append("Wait until every included paid starter has a full seven-day window.")
    if cohort.get("costs_reconciled") is not True:
        holds.append("Reconcile all costs, including unknown provider usage and failures.")
    for name in COUNT_FIELDS + COST_FIELDS:
        value = cohort.get(name)
        valid = type(value) in (int, float) and 0 <= value <= 10**12 and math.isfinite(value)
        if name in COUNT_FIELDS:
            valid = valid and type(value) is int
        if not valid:
            holds.append(f"{name}: provide a finite {'integer' if name in COUNT_FIELDS else 'number'} between 0 and 10^12.")

    if not any(item.split(":")[0] in COUNT_FIELDS + COST_FIELDS for item in holds):
        starts = cohort["paid_starters"]
        exports = cohort["exported_authors"]
        assisted = cohort["assisted_authors"]
        if exports > starts or assisted > starts:
            holds.append("Exported and assisted author counts cannot exceed paid starters.")
        if starts < 10:
            holds.append("Collect at least 10 independent paid starters.")
        if starts:
            metrics["seven_day_export_rate"] = exports / starts
            metrics["operator_assistance_rate"] = assisted / starts
            metrics["support_minutes_per_starter"] = cohort["support_minutes"] / starts
            if exports / starts < 0.8:
                holds.append("Fewer than 80% of paid starters exported within seven days.")
            if assisted / starts > 0.2:
                holds.append("More than 20% of paid starters needed operator assistance.")
            if cohort["support_minutes"] / starts > 10:
                holds.append("Operator effort exceeds 10 minutes per paid starter.")
        cost = sum(cohort[name] for name in COST_FIELDS if name not in (
            "support_minutes", "consumed_credit_revenue_usd",
        ))
        contribution = cohort["consumed_credit_revenue_usd"] - cost
        metrics["contribution_before_acquisition_usd"] = round(contribution, 2)
        if contribution <= 0:
            holds.append("Consumed-credit revenue must exceed fully reconciled delivery costs.")

    return {
        "recommendation": "HOLD" if holds else "READY_FOR_BOUNDED_TEST",
        "holds": holds,
        "metrics": metrics,
        "scope": "Local evidence evaluation only; no production checks or campaign activation performed.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packet", type=Path, help="Reconciled JSON evidence packet")
    args = parser.parse_args()
    try:
        packet = json.loads(args.packet.read_text())
        if not isinstance(packet, dict):
            raise ValueError("Evidence packet must be a JSON object")
        result = evaluate(packet)
    except (OSError, ValueError) as exc:
        print(json.dumps({"recommendation": "HOLD", "holds": [str(exc)]}, indent=2))
        return 2
    print(json.dumps(result, indent=2))
    return 1 if result["holds"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
