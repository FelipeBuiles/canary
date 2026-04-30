"""Credit balance and transaction history endpoints."""

from fastapi import APIRouter, Depends

from ..auth import get_current_user
from ..credits import get_balance_credits
from ..db import get_db

router = APIRouter()


@router.get("/pricing-reference")
def pricing_reference():
    """Return guidance for the pricing reference display."""
    return {
        "notes": [
            "Costs are estimated where you start an action, using that project's model, quality, prompt size, and reference images.",
            "Final charges come from the model usage reported after the request finishes.",
            "Reservations can be higher than the final charge and are released after completion, reset, or failure.",
        ]
    }


@router.get("/balance")
def balance(user_id: str = Depends(get_current_user)):
    credits = get_balance_credits(get_db(), user_id)
    return {"balance_credits": credits}


@router.get("/history")
def history(user_id: str = Depends(get_current_user)):
    rows = (
        get_db()
        .table("credit_ledger")
        .select(
            "id, amount_credits, status, stage, description, created_at, project_id, "
            "provider, model, operation, input_tokens, output_tokens, image_count"
        )
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    )
    return {"transactions": rows.data}
