"""Stage 2: IR → Scenario Events (LLM-assisted).

Uses the Claude API to generate realistic credit card scenario data
from the IR, so the engine can run on any credit card agreement
without hand-written fixtures.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from typing import Optional

from engine.events import (
    Event, AccountOpened, Purchase, CashAdvanceATM, CashAdvanceOther,
    BalanceTransfer, PaymentReceived, PaymentReturned, CycleEnd,
    BillingErrorClaimed, UnauthorizedUse, UnauthorizedUseReported,
)

SYSTEM_PROMPT = """You are a credit card scenario generator. Given a credit card agreement IR (JSON),
generate a realistic 6-month scenario as a JSON array of events.

Each event is an object with a "type" field and parameters. Available event types:

- {"type": "AccountOpened", "day": 1, "cardholder_name": "...", "credit_limit": "5000", "apr_purchase": "10.9", "apr_cash_advance": "12.9", "card_product": "platinum"}
- {"type": "Purchase", "day": N, "amount": "...", "merchant_name": "...", "is_international": false}
- {"type": "CashAdvanceATM", "day": N, "amount": "...", "atm_operator_fee": "3.00"}
- {"type": "BalanceTransfer", "day": N, "amount": "...", "from_institution": "..."}
- {"type": "PaymentReceived", "day": N, "amount": "..."}
- {"type": "PaymentReturned", "day": N, "original_payment_day": M, "amount": "..."}
- {"type": "CycleEnd", "day": N}  (every 30 days: day 30, 60, 90, 120, 150, 180)
- {"type": "BillingErrorClaimed", "day": N, "error_on_statement_day": M, "amount": "...", "description": "...", "method": "written"}
- {"type": "UnauthorizedUse", "day": N, "amount": "...", "tx_type": "purchase"}
- {"type": "UnauthorizedUseReported", "day": N, "method": "oral"}

Rules:
1. Start with AccountOpened on day 1. Use APRs from the IR.
2. Include CycleEnd events every 30 days (day 30, 60, 90, 120, 150, 180).
3. Create a realistic spending pattern with 8-15 purchases.
4. Include at least one of each: cash advance, late payment (missing a due date), on-time payment.
5. Include at least one scenario that triggers a fee (late, over-limit, or returned payment).
6. All amounts as decimal strings (e.g. "1250.00").
7. Make the scenario interesting for a judge — include edge cases.
8. Output ONLY the JSON array, no explanation.
"""


def generate_scenario(ir: dict, api_key: Optional[str] = None) -> list[dict]:
    """Generate scenario event data from a credit card IR.

    Args:
        ir: Credit card agreement IR dict.
        api_key: Anthropic API key.

    Returns:
        list[dict]: Raw event dicts (need hydration via hydrate_events).
    """
    import anthropic

    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ValueError("ANTHROPIC_API_KEY required for scenario generation")

    client = anthropic.Anthropic(api_key=key)

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    "Generate a 6-month credit card scenario for this agreement IR:\n\n"
                    + json.dumps(ir, indent=2)
                )
            }
        ],
    )

    response_text = message.content[0].text.strip()
    if response_text.startswith("```"):
        lines = response_text.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        response_text = "\n".join(lines)

    return json.loads(response_text)


def hydrate_events(raw_events: list[dict]) -> list[Event]:
    """Convert raw event dicts (from LLM or JSON) into typed Event objects."""
    events = []
    for raw in raw_events:
        event_type = raw.get("type", "")
        day = int(raw.get("day", 1))

        if event_type == "AccountOpened":
            events.append(AccountOpened(
                day=day,
                cardholder_name=raw.get("cardholder_name", "Cardholder"),
                credit_limit=Decimal(str(raw.get("credit_limit", "5000"))),
                apr_purchase=Decimal(str(raw.get("apr_purchase", "10.9"))),
                apr_cash_advance=Decimal(str(raw.get("apr_cash_advance", "12.9"))),
                card_product=raw.get("card_product", "platinum"),
                is_joint=raw.get("is_joint", False),
                joint_applicant_name=raw.get("joint_applicant_name", ""),
                home_state=raw.get("home_state", "TX"),
            ))
        elif event_type == "Purchase":
            events.append(Purchase(
                day=day,
                amount=Decimal(str(raw.get("amount", "0"))),
                merchant_name=raw.get("merchant_name", ""),
                merchant_state=raw.get("merchant_state", ""),
                distance_from_home_miles=float(raw.get("distance_from_home_miles", 0)),
                by_user=raw.get("by_user", "primary"),
                is_international=raw.get("is_international", False),
            ))
        elif event_type == "CashAdvanceATM":
            events.append(CashAdvanceATM(
                day=day,
                amount=Decimal(str(raw.get("amount", "0"))),
                by_user=raw.get("by_user", "primary"),
                atm_operator_fee=Decimal(str(raw.get("atm_operator_fee", "0"))),
                is_international=raw.get("is_international", False),
            ))
        elif event_type == "CashAdvanceOther":
            events.append(CashAdvanceOther(
                day=day,
                amount=Decimal(str(raw.get("amount", "0"))),
            ))
        elif event_type == "BalanceTransfer":
            events.append(BalanceTransfer(
                day=day,
                amount=Decimal(str(raw.get("amount", "0"))),
                from_institution=raw.get("from_institution", ""),
            ))
        elif event_type == "PaymentReceived":
            events.append(PaymentReceived(
                day=day,
                amount=Decimal(str(raw.get("amount", "0"))),
                method=raw.get("method", "standard"),
                at_designated_address=raw.get("at_designated_address", True),
            ))
        elif event_type == "PaymentReturned":
            events.append(PaymentReturned(
                day=day,
                original_payment_day=int(raw.get("original_payment_day", 0)),
                amount=Decimal(str(raw.get("amount", "0"))),
            ))
        elif event_type == "CycleEnd":
            events.append(CycleEnd(day=day))
        elif event_type == "BillingErrorClaimed":
            events.append(BillingErrorClaimed(
                day=day,
                error_on_statement_day=int(raw.get("error_on_statement_day", 0)),
                amount=Decimal(str(raw.get("amount", "0"))),
                description=raw.get("description", ""),
                method=raw.get("method", "written"),
            ))
        elif event_type == "UnauthorizedUse":
            events.append(UnauthorizedUse(
                day=day,
                amount=Decimal(str(raw.get("amount", "0"))),
                tx_type=raw.get("tx_type", "purchase"),
            ))
        elif event_type == "UnauthorizedUseReported":
            events.append(UnauthorizedUseReported(
                day=day,
                method=raw.get("method", "oral"),
            ))

    return events
