"""Deterministic IR → English decompiler.

NO LLM. Pure template-based string generation.
Same IR → same English, every time.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any


def decompile_to_english(ir: dict) -> str:
    """Convert a credit card agreement IR to English text.

    This is fully deterministic: same IR always produces identical output.
    """
    sections = []

    sections.append(_render_header(ir))
    sections.append(_render_definitions(ir))
    sections.append(_render_security(ir))
    sections.append(_render_extensions_of_credit(ir))
    sections.append(_render_joint_liability(ir))
    sections.append(_render_authorized_users(ir))
    sections.append(_render_promise_to_pay(ir))
    sections.append(_render_cost_of_credit(ir))
    sections.append(_render_fees(ir))
    sections.append(_render_payment_application(ir))
    sections.append(_render_default(ir))
    sections.append(_render_acceleration(ir))
    sections.append(_render_unauthorized_use(ir))
    sections.append(_render_disputes(ir))
    sections.append(_render_termination(ir))
    sections.append(_render_international(ir))
    sections.append(_render_credit_reporting(ir))
    sections.append(_render_disclosure_table(ir))

    return "\n\n".join(s for s in sections if s)


# ===================================================================
# Section renderers
# ===================================================================

def _render_header(ir: dict) -> str:
    meta = ir.get("meta", {})
    return (
        f"# CREDIT CARD AGREEMENT\n\n"
        f"This Agreement is between {meta.get('issuer_name', '[Issuer]')} "
        f"(\"Credit Union,\" \"we,\" \"us,\" \"our\") and the cardholder (\"you,\" \"your\"). "
        f"This Agreement is governed by the laws of the State of "
        f"{meta.get('governing_law_state', '[State]')} and federal law."
    )


def _render_definitions(ir: dict) -> str:
    return (
        "In this Agreement, \"the Card\" means any credit card issued to you or "
        "those designated by you under the terms of this Agreement. \"Use of the Card\" "
        "means any procedure used by you, or someone authorized by you, to make a "
        "purchase or obtain a cash advance whether or not the purchase or advance is "
        "evidenced by a signed written document. \"Unauthorized use of the Card\" means "
        "the use of the Card by someone other than you who does not have actual, implied, "
        "or apparent authority for such use, and from which you receive no benefit."
    )


def _render_security(ir: dict) -> str:
    si = ir.get("security_interest", {})
    exceptions = si.get("exceptions", [])
    exc_text = _list_to_english(
        [_format_exception(e) for e in exceptions]) if exceptions else "none"

    return (
        "**SECURITY.** You grant us a consensual security interest in "
        f"{_safe(si.get('scope'), 'all individual and joint accounts')} "
        "you have with us now and in the future to secure repayment of credit extensions "
        f"made under this Agreement. Exceptions: {exc_text}."
    )


def _render_extensions_of_credit(ir: dict) -> str:
    illegal = ir.get("illegal_use", {})
    lines = [
        "1) **Extensions of Credit.** If your Application is approved, the Credit Union "
        "may establish a line of credit in your name and cause one or more Cards to be "
        "issued to you or those designated by you."
    ]
    if illegal.get("cardholder_remains_liable"):
        lines.append(
            "You may not use your Card for any illegal purpose or transaction. "
            "If any transaction is ultimately determined to have been for an illegal "
            "purpose, you agree that you will remain liable to us under this Agreement "
            "for any such transaction notwithstanding its illegal nature."
        )
    if illegal.get("constitutes_default"):
        lines.append(
            "You further agree that any illegal use of the Card will be deemed an "
            "act of default under this Agreement."
        )
    return " ".join(lines)


def _render_joint_liability(ir: dict) -> str:
    joint = ir.get("joint_account") or {}
    if not joint:
        return ""

    liability_type = _safe(joint.get("liability_type"), "jointly and individually")

    parts = [
        "2) **Joint Applicant Liability.** If this Agreement is executed by more "
        "than one person, each of you shall be "
        f"{liability_type} "
        "liable to us for all charges made to the account, including applicable fees."
    ]
    if joint.get("each_is_agent_for_other"):
        parts.append(
            "Each of you designates the other as agent for the purpose of making "
            "purchases extended under this Agreement."
        )
    if joint.get("notice_to_one_is_notice_to_all"):
        parts.append("Notice to one of you shall constitute notice to all.")

    withdrawal = joint.get("withdrawal_method")
    if withdrawal:
        parts.append(
            f"Any joint cardholder may remove themselves from responsibility for "
            f"future purchases at any time by notifying us in "
            f"{_safe(withdrawal, 'writing')}."
        )
    if not joint.get("withdrawal_releases_existing_debt", True):
        parts.append(
            "However, removal from the account does not release you from any "
            "liability already incurred."
        )
    return " ".join(parts)


def _render_authorized_users(ir: dict) -> str:
    au = ir.get("authorized_users", {})
    if not au:
        return ""

    parts = [
        "3) **Others Using Your Account.** If you allow anyone else to use your "
        "Card, you will be liable for all credit extended to such persons."
    ]
    reqs = []
    if au.get("revocation_requires_written_notice"):
        reqs.append("notify us in writing")
    if au.get("revocation_requires_card_returned"):
        reqs.append("return the Card with your written notice")
    if reqs:
        parts.append(
            "If you want to end that person's privilege, you must "
            + " and ".join(reqs) + " for it to be effective."
        )
    return " ".join(parts)


def _render_promise_to_pay(ir: dict) -> str:
    mp = ir.get("minimum_payment", {})
    pct = mp.get("percent_of_balance", "3.0")
    floor = mp.get("floor_amount", "15.00")
    threshold = mp.get("pay_in_full_threshold", "15.00")

    return (
        f"5) **Promise to Pay.** You promise to pay us in U.S. dollars for all "
        f"purchases, cash advances, and balance transfers made by you or anyone whom "
        f"you authorize to use the Card or account, plus interest charges and other "
        f"charges or fees, collection costs and attorney's fees as permitted by "
        f"applicable law, and credit in excess of your credit limit that we may extend "
        f"to you.\n\n"
        f"You agree to pay on or before the payment due date shown on the periodic "
        f"statement either the entire New Balance, or the minimum payment shown on the "
        f"statement. The minimum payment will equal {pct}% of the New Balance or "
        f"${floor}, whichever is greater. If the New Balance is ${threshold} or less, "
        f"you will pay in full. You may make extra payments in advance of the due date "
        f"without a penalty, and you may repay any funds advanced at any time without "
        f"a penalty for early payment."
    )


def _render_cost_of_credit(ir: dict) -> str:
    interest = ir.get("interest", {})
    grace = ir.get("grace_period", {})
    rates = interest.get("daily_periodic_rates", [])
    network = ir.get("meta", {}).get("network", "VISA")

    parts = [f"6) **Cost of Credit.** For {network}(R),"]

    rate_clauses = []
    for r in rates:
        rate_clauses.append(
            f"you will pay an INTEREST CHARGE for all advances made against your "
            f"account at the periodic rate of {_fmt_pct(r['daily_rate'])}% per day, "
            f"which has a corresponding ANNUAL PERCENTAGE RATE of {r['apr']}%"
        )
    parts.append("; or ".join(rate_clauses) + ".")

    parts.append(
        "Cash advances (including balance transfers) incur an INTEREST CHARGE "
        "from the date they are posted to the account."
    )

    grace_days = grace.get("purchases_days")
    if grace_days:
        parts.append(
            f"If you have paid your account in full by the due date shown on the "
            f"previous monthly statement, or there is no previous balance, you have "
            f"not less than {grace_days} days to repay your account balance before "
            f"an INTEREST CHARGE on new purchases will be imposed. Otherwise, there "
            f"is no grace period and new purchases will incur an INTEREST CHARGE "
            f"from the date they are posted to the account."
        )

    method = interest.get("method", "")
    if "average_daily_balance" in method:
        parts.append(
            "The INTEREST CHARGE is figured by applying the periodic rate to the "
            "\"balance subject to INTEREST CHARGE\" which is the \"average daily "
            "balance\" of your account, including certain current transactions. "
            "The \"average daily balance\" is arrived at by taking the beginning "
            "balance of your account each day and adding any new cash advances "
            "(including balance transfers), and unless you pay your account in full "
            "by the due date shown on your previous monthly statement or there is no "
            "previous balance, adding in new purchases, and subtracting any payments "
            "or credits and unpaid INTEREST CHARGES. The daily balances for the "
            "billing cycle are then added together and divided by the number of days "
            "in the billing cycle. The result is the \"average daily balance.\" "
            "The INTEREST CHARGE is determined by multiplying the \"average daily "
            "balance\" by the number of days in the billing cycle and applying the "
            "periodic rate to the product."
        )

    return " ".join(parts)


def _render_fees(ir: dict) -> str:
    fees = ir.get("fees", {})
    lines = ["7) **Other Charges.** The following other charges (fees) will be added to your account, as applicable:"]

    fee_items = []

    lp = fees.get("late_payment")
    if lp and isinstance(lp, dict):
        fee_items.append(
            f"* Late Payment Fee. If you are late in making a payment, a late charge "
            f"of ${lp.get('amount', '?')} may be added to your account."
        )

    rp = fees.get("returned_payment")
    if rp and isinstance(rp, dict):
        fee_items.append(
            f"* Returned Payment Fee. If a check, share draft or other order used to "
            f"make a payment on your account is returned unpaid, you may be charged a "
            f"fee of ${rp.get('amount', '?')} for each item returned. In no event will the "
            f"Returned Payment Fee exceed the minimum payment amount for the applicable "
            f"statement period."
        )

    ol = fees.get("over_limit")
    if ol and isinstance(ol, dict):
        recurring = ""
        if ol.get("recurring"):
            recurring = (
                " You will be charged the fee each subsequent month until your New "
                "Balance on the statement date, less any fees imposed during the cycle, "
                "is below your credit limit."
            )
        fee_items.append(
            f"* Over Credit Limit Fee. You may be charged a fee of ${ol.get('amount', '?')} "
            f"on a statement date if your New Balance, less any fees imposed during "
            f"the cycle, is over your credit limit.{recurring}"
        )

    cr = fees.get("card_replacement")
    if cr:
        cr_amount = cr.get("amount", cr) if isinstance(cr, dict) else cr
        fee_items.append(
            f"* Card Replacement Fee. You may be charged ${cr_amount} "
            f"for each replacement Card that is issued to you for any reason."
        )

    dc = fees.get("document_copy")
    if dc and isinstance(dc, dict):
        waiver = ""
        if dc.get("waived_on_cu_billing_error"):
            waiver = " (except when the request is made in conjunction with a billing error made by the Credit Union)"
        fee_items.append(
            f"* Document Copy Fee. You may be charged ${dc['amount']} for each copy "
            f"of a sales draft or statement that you request{waiver}."
        )

    atm = fees.get("atm_operator_fee", "")
    if atm:
        fee_items.append(
            "* ATM Fee. If you obtain a cash advance by using an automated teller "
            "machine, you may be charged any amounts imposed upon the Credit Union "
            "by the owner or operator of the machine. Any charge made under this "
            "paragraph will be added to the balance of your account and treated as "
            "a purchase."
        )

    fee_items.append(
        "* Collection Cost Fee. You agree to pay all reasonable costs of collection, "
        "including court costs and attorney's fees imposed and any costs incurred in "
        "the recovery of the Card."
    )

    return lines[0] + "\n" + "\n".join(fee_items)


def _render_payment_application(ir: dict) -> str:
    pa = ir.get("payment_application") or {}
    min_order = pa.get("minimum_payment_order") or []
    excess = pa.get("excess_payment_order") or "highest rate first"

    order_text = ", then to ".join(
        _safe(o) for o in min_order if o
    )

    return (
        f"10) **Crediting of Payments.** All required minimum payments on your "
        f"account will be applied first to {order_text}. "
        f"Payments made in excess of the required minimum payment will be applied "
        f"first to the balances with the {_safe(excess, 'highest rate first')}, if applicable."
    )


def _render_default(ir: dict) -> str:
    triggers = ir.get("default_triggers") or []
    parts = ["11) **Default. You will be in default:**"]
    for i, t in enumerate(triggers, 1):
        condition = _safe(t.get("condition"), "unspecified")
        parts.append(f"({i}) if {condition};")
    return " ".join(parts)


def _render_acceleration(ir: dict) -> str:
    dc = ir.get("default_consequences", {})
    parts = ["12) **Acceleration.**"]
    if dc.get("acceleration"):
        parts.append(
            "If you are in default, the Credit Union may, without prior notice to you, "
            "call any amounts you still owe immediately due and payable plus INTEREST "
            "CHARGES, which shall continue to accrue until the entire amount is paid."
        )
    if dc.get("notice_waived_by_cardholder"):
        parts.append(
            "You expressly waive any right to notice or demand, including but not "
            "limited to, demand upon default, notice of intention to accelerate, and "
            "notice of acceleration."
        )
    if dc.get("card_surrender_on_demand"):
        parts.append(
            "The Card remains the property of the Credit Union at all times, and "
            "you agree to immediately surrender the Card upon demand of the Credit Union."
        )
    return " ".join(parts)


def _render_unauthorized_use(ir: dict) -> str:
    liab = ir.get("liability", {})
    cap = liab.get("unauthorized_use_cap", "50.00")
    zero = liab.get("visa_zero_liability", False)
    exceptions = liab.get("zero_liability_exceptions", [])

    parts = [
        "9) **Liability for Unauthorized Use.** You may be liable for the "
        "unauthorized use of your Card."
    ]
    if zero:
        exc_text = ", ".join(e.replace("_", " ") for e in exceptions)
        parts.append(
            f"Under VISA's zero liability policy, you will not be liable for "
            f"unauthorized use of your VISA Card once you notify us orally or in "
            f"writing of the loss, theft, or possible unauthorized use. "
            f"VISA's zero liability policy does not apply in the case of: {exc_text}."
        )
    parts.append(
        f"In any case, your liability will not exceed ${cap}."
    )
    return " ".join(parts)


def _render_disputes(ir: dict) -> str:
    disputes = ir.get("disputes", {})
    be = disputes.get("billing_error", {})
    pd = disputes.get("purchase_dispute", {})

    parts = ["## YOUR BILLING RIGHTS\n"]

    if be:
        parts.append(
            f"If you think there is an error on your statement, write to us. "
            f"You must contact us within {be.get('filing_window_days', 60)} days "
            f"after the error appeared on your statement. "
            f"You must notify us of any potential errors in writing."
        )
        parts.append(
            f"When we receive your letter, within {be.get('ack_deadline_days', 30)} "
            f"days we must tell you that we received your letter. "
            f"Within {be.get('resolution_deadline_days', 90)} days we must either "
            f"correct the error or explain to you why we believe your statement "
            f"is correct."
        )
        penalty = be.get("cu_failure_penalty", "50.00")
        parts.append(
            f"If we do not follow all of the rules above, you do not have to pay "
            f"the first ${penalty} of the amount you question even if your bill "
            f"is correct."
        )

    if pd:
        miles = pd.get("geographic_limit_same_state_or_miles", 100)
        min_amt = pd.get("minimum_purchase_amount", "50.00")
        parts.append(
            f"\n## Your Rights if You are Dissatisfied with Your Credit Card Purchases\n"
            f"The purchase must have been made in your home state or within "
            f"{miles} miles of your current mailing address, and the purchase price "
            f"must have been more than ${min_amt}."
        )
        exceptions = pd.get("geographic_exceptions", [])
        if exceptions:
            exc_text = " or ".join(e.replace("_", " ") for e in exceptions)
            parts.append(
                f"Neither of these are necessary if {exc_text}."
            )
        if pd.get("requires_card_used_directly"):
            parts.append("You must have used your credit card for the purchase.")
        if pd.get("requires_not_fully_paid"):
            parts.append("You must not yet have fully paid for the purchase.")
        if pd.get("requires_good_faith_merchant_attempt"):
            parts.append(
                "You must have tried in good faith to correct the problem "
                "with the merchant."
            )

    return "\n".join(parts)


def _render_termination(ir: dict) -> str:
    term = ir.get("termination") or {}
    parts = ["18) **Termination or Changes.**"]
    if term.get("cu_can_terminate"):
        parts.append(
            "The Credit Union may terminate this Agreement at any time subject "
            "to such notice as may be required by applicable law."
        )
    method = term.get("cardholder_method")
    if method:
        parts.append(
            f"You may terminate this Agreement, by {_safe(method, 'written notice')}, "
            f"as to future advances at any time."
        )
    surviving = term.get("surviving_obligations") or []
    if surviving:
        items = ", ".join(_safe(s) for s in surviving if s)
        parts.append(
            f"Termination by either party shall not affect your obligation to "
            f"repay {items}."
        )
    if term.get("use_after_terms_change_notice_binds_existing_balance"):
        parts.append(
            "If you use your Card or account to make a purchase or cash advance "
            "after having been given notice of a change in terms, you agree that "
            "the existing balance in your account at the time of that use will be "
            "subject to the new terms."
        )
    return " ".join(parts)


def _render_international(ir: dict) -> str:
    intl = ir.get("international_transactions", {})
    if not intl:
        return ""
    fee_pct = intl.get("foreign_transaction_fee_pct", "1.0")
    return (
        f"16) **International Transactions.** If you effect an international "
        f"transaction with your VISA Card, a Foreign Transaction Fee of up to "
        f"{fee_pct}% will apply to all international purchase, cash disbursement, "
        f"and account credit transactions even if there is no currency conversion. "
        f"There is no grace period within which to repay international transactions "
        f"in order to avoid the Foreign Transaction Fee."
    )


def _render_credit_reporting(ir: dict) -> str:
    cr = ir.get("credit_reporting", {})
    if not cr:
        return ""
    address = cr.get("notification_address", "[Address]")
    return (
        f"20) **Notification Address for Information Reported to Consumer "
        f"Reporting Agencies.** We may report the status and payment history "
        f"of your account to credit reporting agencies each month. If you believe "
        f"that the information we have reported is inaccurate or incomplete, "
        f"please notify us in writing at {address}."
    )


def _render_disclosure_table(ir: dict) -> str:
    products = ir.get("products", [])
    fees = ir.get("fees", {})

    lines = [
        "## Credit Disclosure\n",
        "| Item | Details |",
        "| :--- | :--- |",
    ]

    for p in products:
        apr_p = p.get("apr_purchases") or {}
        apr_ca = p.get("apr_cash_advances") or {}
        apr_bt = p.get("apr_balance_transfers") or {}

        lines.append(
            f"| **APR for Purchases ({p['name']})** | "
            f"{apr_p.get('min', '?')}%-{apr_p.get('max', '?')}% |"
        )
        lines.append(
            f"| **APR for Cash Advances ({p['name']})** | "
            f"{apr_ca.get('min', '?')}%-{apr_ca.get('max', '?')}% |"
        )
        if apr_bt and apr_bt.get("intro_rate") is not None:
            intro = apr_bt.get("intro_rate", "0")
            months = apr_bt.get("intro_period_months", "?")
            post = apr_bt.get("post_intro", {})
            lines.append(
                f"| **APR for Balance Transfers ({p['name']})** | "
                f"{intro}% introductory for {months} months, "
                f"then {post.get('min', '?')}%-{post.get('max', '?')}% |"
            )

    lines.append(f"| **Annual Fee** | ${fees.get('annual', '0.00')} |")
    lp_fee = fees.get('late_payment')
    lp_amt = lp_fee.get('amount', '?') if isinstance(lp_fee, dict) else (lp_fee or '?')
    lines.append(f"| **Late Payment Fee** | Up to ${lp_amt} |")
    rp_fee = fees.get('returned_payment')
    rp_amt = rp_fee.get('amount', '?') if isinstance(rp_fee, dict) else (rp_fee or '?')
    lines.append(f"| **Returned Payment Fee** | Up to ${rp_amt} |")
    lines.append(
        f"| **Foreign Transaction Fee** | Up to {fees.get('foreign_transaction_pct', '?')}% |"
    )

    return "\n".join(lines)


# ===================================================================
# Helpers
# ===================================================================

def _fmt_pct(value: str) -> str:
    """Format a decimal rate as a percentage string (e.g. '0.0002986' → '0.02986')."""
    d = Decimal(value) * 100
    return str(d)


def _safe(val, default: str = "") -> str:
    """Safely convert a value to string, handling None."""
    if val is None:
        return default
    return str(val).replace("_", " ")


def _format_exception(exc: str) -> str:
    return exc.replace("_", " ")


def _list_to_english(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"
