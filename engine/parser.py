"""Stage 1: Contract Markdown → Credit Card IR (LLM-assisted).

Uses the Claude API to extract structured credit card agreement
terms from raw markdown into our IR JSON schema.
"""

from __future__ import annotations

import json
import os
from typing import Optional

SYSTEM_PROMPT = """You are a legal document parser specialized in credit card agreements.
Given a credit card agreement in Markdown format, extract ALL terms into the following
JSON structure. Be precise with numbers — use exact values from the document.

Output ONLY valid JSON matching this schema (no markdown fences, no explanation):

{
  "meta": {
    "issuer_name": "string",
    "issuer_address": "string",
    "issuer_phone": "string",
    "card_services_address": "string",
    "network": "string (e.g. VISA, Mastercard)",
    "governing_law_state": "string",
    "source_clause": "string"
  },
  "products": [
    {
      "id": "string",
      "name": "string",
      "annual_fee": "decimal string",
      "apr_purchases": {"min": "decimal", "max": "decimal"},
      "apr_cash_advances": {"min": "decimal", "max": "decimal"},
      "apr_balance_transfers": {
        "intro_rate": "decimal or null",
        "intro_period_months": "int or null",
        "post_intro": {"min": "decimal", "max": "decimal"}
      }
    }
  ],
  "interest": {
    "method": "string (e.g. average_daily_balance_including_current)",
    "daily_periodic_rates": [
      {"apr": "decimal", "daily_rate": "decimal"}
    ],
    "minimum_interest": "decimal"
  },
  "grace_period": {
    "purchases_days": "int",
    "condition": "string",
    "cash_advances": "none or description",
    "balance_transfers": "none or description"
  },
  "minimum_payment": {
    "percent_of_balance": "decimal",
    "floor_amount": "decimal",
    "pay_in_full_threshold": "decimal"
  },
  "fees": {
    "annual": "decimal",
    "late_payment": {"amount": "decimal"},
    "returned_payment": {"amount": "decimal", "cap": "string"},
    "over_limit": {"amount": "decimal", "recurring": true/false},
    "card_replacement": "decimal",
    "document_copy": {"amount": "decimal", "waived_on_cu_billing_error": true/false},
    "foreign_transaction_pct": "decimal",
    "atm_operator_fee": "passthrough",
    "convenience_check_copy": "decimal",
    "convenience_check_stop_payment": "decimal",
    "convenience_check_nsf": "decimal"
  },
  "payment_application": {
    "minimum_payment_order": ["collection_costs", "interest_and_fees", "principal_lowest_rate"],
    "excess_payment_order": "highest_rate_first"
  },
  "security_interest": {
    "scope": "string",
    "exceptions": ["string"]
  },
  "liability": {
    "unauthorized_use_cap": "decimal",
    "visa_zero_liability": true/false,
    "zero_liability_exceptions": ["string"]
  },
  "default_triggers": [
    {"code": "D1", "condition": "string"}
  ],
  "default_consequences": {
    "acceleration": true/false,
    "notice_required": true/false,
    "card_surrender_on_demand": true/false,
    "collection_costs": "string"
  },
  "disputes": {
    "billing_error": {
      "filing_window_days": "int",
      "filing_method": "string",
      "ack_deadline_days": "int",
      "resolution_deadline_days": "int",
      "cardholder_reject_window_days": "int",
      "cu_failure_penalty": "decimal"
    },
    "purchase_dispute": {
      "geographic_limit_same_state_or_miles": "int",
      "minimum_purchase_amount": "decimal",
      "geographic_exceptions": ["string"],
      "requires_card_used_directly": true/false,
      "requires_not_fully_paid": true/false,
      "requires_good_faith_merchant_attempt": true/false
    }
  },
  "joint_account": {
    "liability_type": "string",
    "each_is_agent_for_other": true/false,
    "notice_to_one_is_notice_to_all": true/false,
    "withdrawal_method": "string",
    "withdrawal_releases_existing_debt": true/false
  },
  "authorized_users": {
    "cardholder_liable_for_all_charges": true/false,
    "revocation_requires_written_notice": true/false,
    "revocation_requires_card_returned": true/false
  },
  "termination": {
    "cu_can_terminate": true/false,
    "cardholder_method": "string",
    "surviving_obligations": ["string"],
    "use_after_terms_change_notice_binds_existing_balance": true/false
  },
  "billing_cycle_days": "int",
  "payment_due_days_after_statement": "int"
}

Extract values EXACTLY as stated in the contract. For daily periodic rates,
use the exact decimal values given in the document (do not compute from APR).
If a field is not mentioned in the contract, use null.
"""


def parse_contract(markdown_path: str, api_key: Optional[str] = None) -> dict:
    """Parse a credit card agreement markdown file into IR JSON.

    Args:
        markdown_path: Path to the .md contract file.
        api_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.

    Returns:
        dict: The credit card agreement IR.
    """
    import anthropic

    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ValueError("ANTHROPIC_API_KEY required for LLM parsing")

    with open(markdown_path, "r") as f:
        contract_text = f.read()

    client = anthropic.Anthropic(api_key=key)

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Parse this credit card agreement into the IR JSON schema:\n\n{contract_text}"
            }
        ],
    )

    response_text = message.content[0].text.strip()

    # Strip markdown fences if present
    if response_text.startswith("```"):
        lines = response_text.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        response_text = "\n".join(lines)

    return json.loads(response_text)
