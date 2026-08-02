from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from novel_to_comic.server.routers import backoffice
from novel_to_comic.server.runtime_environment import stripe_environment_snapshot


def _body(key: str = "support-1234") -> backoffice.GrantCreditsRequest:
    return backoffice.GrantCreditsRequest(
        amount_credits=375,
        reason="Recovery for a failed generation",
        operator="jb",
        idempotency_key=key,
    )


def test_stripe_snapshot_marks_local_test_mode(monkeypatch):
    monkeypatch.setenv("CANARY_ENV", "dev")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_example")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_example")

    result = stripe_environment_snapshot()

    assert result["app_environment"] == "dev"
    assert result["stripe_mode"] == "sandbox"
    assert result["expected_stripe_mode"] == "sandbox"
    assert result["mode_matches_app"] is True
    assert result["safe_for_real_customers"] is False


def test_stripe_snapshot_flags_production_test_key(monkeypatch):
    monkeypatch.setenv("CANARY_ENV", "production")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_example")

    result = stripe_environment_snapshot()

    assert result["app_environment"] == "production"
    assert result["stripe_mode"] == "sandbox"
    assert result["mode_matches_app"] is False
    assert "mode" in result["live_money_warning"]


def test_credit_grant_is_idempotent_and_not_a_stripe_charge():
    ledger = MagicMock()
    ledger.select.return_value = ledger
    ledger.eq.return_value = ledger
    ledger.limit.return_value = ledger
    ledger.insert.return_value = ledger
    ledger.execute.side_effect = [
        SimpleNamespace(data=[]),
        SimpleNamespace(
            data=[
                {
                    "id": "ledger-grant-1",
                    "user_id": "user-1",
                    "amount_credits": 375,
                    "operation": "operator_grant",
                }
            ]
        ),
    ]
    db = MagicMock()
    db.table.return_value = ledger

    with (
        patch.object(backoffice, "get_db", return_value=db),
        patch.object(backoffice, "capture_server_event") as capture,
        patch.object(backoffice, "stripe_environment_snapshot", return_value={"stripe_mode": "sandbox"}),
    ):
        result = backoffice.grant_credits("user-1", _body())

    assert result["status"] == "granted"
    assert result["amount_credits"] == 375
    assert result["idempotent"] is False
    assert result["stripe_charge"] is False
    capture.assert_called_once()
    inserted = ledger.insert.call_args.args[0]
    assert inserted["operation"] == "operator_grant"
    assert inserted["provider"] == "operator"
    assert inserted["usage_call_id"] == "operator-grant:support-1234"


def test_existing_credit_grant_retry_does_not_insert_again():
    ledger = MagicMock()
    ledger.select.return_value = ledger
    ledger.eq.return_value = ledger
    ledger.limit.return_value = ledger
    ledger.execute.return_value = SimpleNamespace(
        data=[
            {
                "id": "ledger-grant-1",
                "user_id": "user-1",
                "amount_credits": 375,
                "operation": "operator_grant",
            }
        ]
    )
    db = MagicMock()
    db.table.return_value = ledger

    with (
        patch.object(backoffice, "get_db", return_value=db),
        patch.object(backoffice, "stripe_environment_snapshot", return_value={"stripe_mode": "live"}),
    ):
        result = backoffice.grant_credits("user-1", _body())

    assert result["idempotent"] is True
    ledger.insert.assert_not_called()


def test_user_snapshot_combines_real_balance_and_provider_errors(tmp_path):
    user = SimpleNamespace(
        id="user-1",
        email="maya@example.com",
        user_metadata={"full_name": "Maya Chen"},
        email_confirmed_at="2026-07-18T12:00:00+00:00",
        phone_confirmed_at=None,
        last_sign_in_at="2026-08-01T12:00:00+00:00",
        created_at="2026-07-18T12:00:00+00:00",
        banned_until=None,
        is_anonymous=False,
        is_sso_user=False,
    )
    app = SimpleNamespace(state=SimpleNamespace(projects_dir=tmp_path))

    result = backoffice._make_user(
        user,
        project_rows=[],
        ledger_rows=[
            {
                "user_id": "user-1",
                "amount_credits": 420,
                "status": "settled",
                "gross_amount_cents": 4200,
            }
        ],
        usage_rows=[
            {
                "user_id": "user-1",
                "stage": "draw",
                "status": "failed",
                "error_type": "timeout",
                "error_message": "Provider timed out",
                "created_at": "2026-08-01T12:01:00+00:00",
            }
        ],
        events=[],
        jobs=[],
        app=app,
    )

    assert result["name"] == "Maya Chen"
    assert result["credits"] == 420
    assert result["current_stage"] == "No active project"
    assert result["error_count"] == 1
    assert result["last_error"]["message"] == "Provider timed out"
    assert "errors" in result["tags"]
