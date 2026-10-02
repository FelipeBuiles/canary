from pathlib import Path

import pytest

from novel_to_comic.config import Config
from novel_to_comic.server.credits import estimate_stage_credit_breakdown
from novel_to_comic.server.routers.billing import CREDIT_PACKAGES
from novel_to_comic.state import create_initial_state


def test_extract_estimate_for_typical_project_stays_in_sane_range(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # Production economics per docs/proposals/pricing-and-margin.md:
    # markup 2.0 (~48% net GM after Stripe), 100 credits per provider USD.
    monkeypatch.setenv("PULP_CREDITS_PER_PROVIDER_USD", "100")
    monkeypatch.setenv("PULP_MODEL_COST_MARKUP", "2.0")
    monkeypatch.setenv("PULP_RESERVATION_BUFFER", "1.25")

    novel_path = tmp_path / "novel.txt"
    novel_path.write_text("A short source sentence. " * (120 * 1024 // 25))
    state = create_initial_state("demo", str(novel_path))
    config = Config(extraction_model="gemini-3.8-flash")

    estimate = estimate_stage_credit_breakdown(config, tmp_path, state, "extract")

    # Gemini 3.8 Flash thinking cannot be disabled; its 4K-token thinking
    # allowance per call lifts this from ~60 to ~88 credits.
    assert estimate["estimate_credits"] in range(6, 101)


def test_credit_packages_match_recommended_pricing():
    """Lock the four-tier pricing from docs/proposals/pricing-and-margin.md.

    Catches accidental edits to CREDIT_PACKAGES that would silently change
    what users pay at checkout. Update this test only when pricing is
    deliberately revised.
    """
    assert set(CREDIT_PACKAGES) == {"starter", "standard", "creator", "studio"}
    assert CREDIT_PACKAGES["starter"] == {
        "label": "1,200 credits", "price_cents": 1200, "credits": 1200,
    }
    assert CREDIT_PACKAGES["standard"] == {
        "label": "3,000 credits", "price_cents": 3000, "credits": 3000,
    }
    assert CREDIT_PACKAGES["creator"] == {
        "label": "7,500 credits", "price_cents": 7000, "credits": 7500,
    }
    assert CREDIT_PACKAGES["studio"] == {
        "label": "18,000 credits", "price_cents": 15000, "credits": 18000,
    }


@pytest.mark.parametrize(
    ("package_id", "min_net_gm_pct"),
    [("starter", 40), ("standard", 40), ("creator", 40), ("studio", 30)],
)
def test_every_package_clears_minimum_margin_after_stripe(package_id, min_net_gm_pct):
    """No package sells below the floor margin once Stripe's 2.9% + $0.30 is paid.

    Bulk tiers discount via more credits per dollar, so their net GM is lower
    than the base tiers; the floor reflects that. See pricing-and-margin.md §d.
    """
    pkg = CREDIT_PACKAGES[package_id]
    price_usd = pkg["price_cents"] / 100
    # Provider cost underlying the credits, at markup 2.0 / 100 credits per USD.
    provider_cost_usd = pkg["credits"] / 100 / 2.0
    stripe_fee = price_usd * 0.029 + 0.30
    net_revenue = price_usd - stripe_fee
    gm = (net_revenue - provider_cost_usd) / price_usd * 100
    assert gm >= min_net_gm_pct, f"{package_id}: {gm:.1f}% GM < {min_net_gm_pct}% floor"
