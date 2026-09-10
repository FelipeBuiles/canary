"""Acquisition must stay on hold when evidence is missing or contradictory."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("launch_scorecard", ROOT / "scripts/launch_scorecard.py")
assert spec and spec.loader
scorecard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scorecard)


@pytest.fixture
def packet():
    # Synthetic boundary case; never a record of production readiness.
    return {
        "schema_version": 1,
        "release_sha": "synthetic-test-revision",
        "severe_incident_open": False,
        "gates": {name: {"status": "passed", "evidence": "test fixture"} for name in scorecard.GATES},
        "cohort": {
            "seven_day_window_closed": True, "costs_reconciled": True,
            "paid_starters": 10, "exported_authors": 8, "assisted_authors": 2,
            "support_minutes": 100, "consumed_credit_revenue_usd": 100,
            "provider_cost_usd": 25, "payment_fees_usd": 5, "consumed_credit_refunds_usd": 0,
            "variable_infrastructure_usd": 5, "support_cost_usd": 20,
        },
    }


def test_template_is_hold():
    packet = json.loads((ROOT / "docs/ops/launch-scorecard-template.json").read_text())
    assert scorecard.evaluate(packet)["recommendation"] == "HOLD"


def test_boundary_can_recommend_small_test(packet):
    result = scorecard.evaluate(packet)
    assert result["recommendation"] == "READY_FOR_BOUNDED_TEST"
    assert result["metrics"]["contribution_before_acquisition_usd"] == 45


@pytest.mark.parametrize("field,value", [
    ("paid_starters", 9), ("exported_authors", 7), ("exported_authors", 11),
    ("assisted_authors", 3), ("support_minutes", 101),
    ("provider_cost_usd", 100), ("consumed_credit_refunds_usd", -1), ("support_cost_usd", None),
    ("paid_starters", True), ("exported_authors", 8.0),
    ("provider_cost_usd", float("nan")), ("provider_cost_usd", float("inf")),
    ("paid_starters", 10**400),
    ("costs_reconciled", False), ("seven_day_window_closed", False),
])
def test_bad_or_incomplete_cohort_holds(packet, field, value):
    packet["cohort"][field] = value
    assert scorecard.evaluate(packet)["recommendation"] == "HOLD"


def test_claimed_gate_without_evidence_holds(packet):
    packet["gates"]["billing_isolation"]["evidence"] = ""
    assert scorecard.evaluate(packet)["recommendation"] == "HOLD"


def test_open_incident_holds_even_with_good_metrics(packet):
    packet["severe_incident_open"] = True
    assert scorecard.evaluate(packet)["recommendation"] == "HOLD"


def test_malformed_sections_hold(packet):
    packet["gates"] = []
    packet["cohort"] = None
    assert scorecard.evaluate(packet)["recommendation"] == "HOLD"
