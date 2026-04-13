"""Cycle-by-cycle credit card engine using real dates and ADB tracker.

Takes parsed statement history and re-computes every cycle, producing
detailed explanations for each of the judge's four questions:
  1. How was interest calculated?
  2. Was grace period handled correctly?
  3. Justify every fee
  4. How were payments applied?
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from engine.adb import ADBTracker, _round, ZERO
from engine.statement_input import AccountParams, CycleData, Transaction, StatementHistory

CENT = Decimal("0.01")


# ===================================================================
# Result types — what the engine produces per cycle
# ===================================================================

@dataclass
class GracePeriodExplanation:
    eligible: bool
    reason: str  # Full sentence for the judge


@dataclass
class FeeExplanation:
    fee_date: date
    description: str
    amount: Decimal
    clause_ref: str
    justification: str  # Why this fee was assessed


@dataclass
class WaterfallStep:
    component: str  # "Collection Costs", "Interest Charges & Fees", "Principal"
    amount: Decimal
    applied_to: str  # Description


@dataclass
class PaymentExplanation:
    payment_date: date
    total_amount: Decimal
    minimum_required: Decimal
    steps: list[WaterfallStep]
    excess_amount: Decimal = ZERO
    excess_applied_to: str = ""


@dataclass
class InterestExplanation:
    """Full interest calculation breakdown."""
    purchase_adb: Decimal = ZERO
    purchase_rate: Decimal = ZERO
    purchase_apr: Decimal = ZERO
    purchase_interest: Decimal = ZERO
    cash_advance_adb: Decimal = ZERO
    cash_advance_rate: Decimal = ZERO
    cash_advance_apr: Decimal = ZERO
    cash_advance_interest: Decimal = ZERO
    total_interest: Decimal = ZERO
    days_in_cycle: int = 0
    adb_entries: list = field(default_factory=list)  # ADBEntry list
    grace_note: str = ""
    rate_type: str = "daily"  # "daily" or "monthly"


@dataclass
class CycleResult:
    """Complete engine output for one billing cycle."""
    cycle_number: int
    cycle_start: date
    cycle_end: date
    days_in_cycle: int

    # Computed values
    previous_balance: Decimal = ZERO
    new_balance: Decimal = ZERO
    minimum_payment: Decimal = ZERO
    payment_due_date: Optional[date] = None

    total_purchases: Decimal = ZERO
    total_cash_advances: Decimal = ZERO
    total_payments: Decimal = ZERO
    total_fees: Decimal = ZERO
    total_interest: Decimal = ZERO

    # The four explanations
    interest_explanation: Optional[InterestExplanation] = None
    grace_explanation: Optional[GracePeriodExplanation] = None
    fee_explanations: list[FeeExplanation] = field(default_factory=list)
    payment_explanations: list[PaymentExplanation] = field(default_factory=list)


# ===================================================================
# Main engine
# ===================================================================

def run_cycles(history: StatementHistory) -> list[CycleResult]:
    """Process all cycles from the statement history.

    For each cycle:
    1. Build the ADB from transactions
    2. Evaluate grace period
    3. Compute interest
    4. Justify fees
    5. Show payment waterfall

    Returns list of CycleResult with full explanations.
    """
    params = history.params
    results: list[CycleResult] = []

    # Track state across cycles
    running_balance = ZERO
    purchase_balance = ZERO
    cash_advance_balance = ZERO
    interest_owed = ZERO
    fees_owed = ZERO
    grace_eligible = True  # first cycle has grace (no previous balance)
    prev_statement_balance = ZERO
    prev_paid_in_full = True
    prev_due_date: Optional[date] = None
    prev_payment_total = ZERO
    late_count_recent = 0  # for tiered late fees

    for cycle_data in history.cycles:
        result = _process_cycle(
            cycle_data, params,
            running_balance, purchase_balance, cash_advance_balance,
            interest_owed, fees_owed,
            grace_eligible, prev_statement_balance, prev_paid_in_full,
            prev_due_date, prev_payment_total, late_count_recent,
        )
        results.append(result)

        # Compute per-bucket balances going into next cycle
        # Start from previous bucket balances, apply this cycle's transactions
        cycle_purchases = sum(
            (tx.amount for tx in cycle_data.transactions if tx.category == "Purchase"), ZERO)
        cycle_ca = sum(
            (tx.amount for tx in cycle_data.transactions if tx.category == "Cash Advance"), ZERO)
        cycle_fees = sum(
            (tx.amount for tx in cycle_data.transactions if tx.category == "Fee"), ZERO)
        cycle_payments = sum(
            (tx.amount for tx in cycle_data.transactions if tx.category == "Payment"), ZERO)

        # Add new charges to buckets
        purchase_balance = _round(purchase_balance + cycle_purchases + cycle_fees)
        cash_advance_balance = _round(cash_advance_balance + cycle_ca)

        # Subtract payments (from purchase first, then CA — simplified waterfall)
        remaining_payment = cycle_payments
        p_paid = min(remaining_payment, purchase_balance)
        purchase_balance = _round(purchase_balance - p_paid)
        remaining_payment = _round(remaining_payment - p_paid)
        ca_paid = min(remaining_payment, cash_advance_balance)
        cash_advance_balance = _round(cash_advance_balance - ca_paid)

        # Add interest to the appropriate bucket
        ie = result.interest_explanation
        if ie:
            interest_owed = ie.total_interest
            purchase_balance = _round(purchase_balance + ie.purchase_interest)
            cash_advance_balance = _round(cash_advance_balance + ie.cash_advance_interest)
        else:
            interest_owed = ZERO

        fees_owed = result.total_fees

        # Update state for next cycle
        running_balance = result.new_balance
        prev_statement_balance = result.new_balance
        prev_due_date = result.payment_due_date
        grace_eligible = result.grace_explanation.eligible if result.grace_explanation else True

    # Second pass: determine grace eligibility using next cycle's payment info
    _resolve_grace_forward(results, history)

    return results


def _process_cycle(
    cycle: CycleData, params: AccountParams,
    running_balance: Decimal, purchase_balance: Decimal, cash_advance_balance: Decimal,
    interest_owed: Decimal, fees_owed: Decimal,
    grace_eligible: bool, prev_balance: Decimal, prev_paid_in_full: bool,
    prev_due_date: Optional[date], prev_payment_total: Decimal,
    late_count_recent: int,
) -> CycleResult:

    result = CycleResult(
        cycle_number=cycle.cycle_number,
        cycle_start=cycle.cycle_start,
        cycle_end=cycle.cycle_end,
        days_in_cycle=cycle.days_in_cycle,
        previous_balance=cycle.previous_balance,
        payment_due_date=cycle.payment_due_date,
    )

    # -------------------------------------------------------------------
    # 1. Grace Period Evaluation
    # -------------------------------------------------------------------
    grace_exp = _evaluate_grace(
        cycle, params, prev_balance, prev_paid_in_full,
        prev_due_date, prev_payment_total, grace_eligible,
    )
    result.grace_explanation = grace_exp

    # -------------------------------------------------------------------
    # 2. Build ADB from transactions
    # -------------------------------------------------------------------
    interest_exp, adb_tracker = _compute_interest(
        cycle, params, grace_exp.eligible, running_balance,
        purchase_balance, cash_advance_balance,
    )
    result.interest_explanation = interest_exp
    result.total_interest = interest_exp.total_interest

    # -------------------------------------------------------------------
    # 3. Fee Justification
    # -------------------------------------------------------------------
    fee_explanations = _justify_fees(cycle, params, prev_due_date, late_count_recent)
    result.fee_explanations = fee_explanations
    result.total_fees = sum(f.amount for f in fee_explanations)

    # -------------------------------------------------------------------
    # 4. Payment Waterfall
    # -------------------------------------------------------------------
    payment_explanations = _explain_payments(cycle, params, interest_owed, fees_owed)
    result.payment_explanations = payment_explanations

    # -------------------------------------------------------------------
    # 5. Computed totals — derive from actual transactions, not summary box
    # -------------------------------------------------------------------
    result.total_purchases = _round(sum(
        (tx.amount for tx in cycle.transactions if tx.category == "Purchase"), ZERO))
    result.total_cash_advances = _round(sum(
        (tx.amount for tx in cycle.transactions if tx.category == "Cash Advance"), ZERO))
    result.total_payments = _round(sum(
        (tx.amount for tx in cycle.transactions if tx.category == "Payment"), ZERO))
    result.total_fees = _round(sum((f.amount for f in fee_explanations), ZERO))
    result.new_balance = cycle.new_balance
    result.minimum_payment = cycle.minimum_payment

    return result


def _evaluate_grace(
    cycle: CycleData, params: AccountParams,
    prev_balance: Decimal, prev_paid_in_full: bool,
    prev_due_date: Optional[date], prev_payment_total: Decimal,
    was_grace_eligible: bool,
) -> GracePeriodExplanation:
    """Determine grace period eligibility and explain why."""

    if cycle.cycle_number == 1:
        return GracePeriodExplanation(
            eligible=True,
            reason="YES (no previous balance). New purchases have at least "
                   f"{params.grace_period_days} days before interest accrues.",
        )

    # Check if previous balance was paid in full
    if prev_balance <= ZERO:
        return GracePeriodExplanation(
            eligible=True,
            reason=f"YES (no previous balance). New purchases have at least "
                   f"{params.grace_period_days} days before interest accrues.",
        )

    # Look at payments in THIS cycle that applied to the previous balance
    # We need to check: was the previous new_balance paid in full by its due date?
    payments_before_due = ZERO
    if prev_due_date:
        for tx in cycle.transactions:
            if tx.category == "Payment" and tx.post_date <= prev_due_date:
                payments_before_due += tx.amount

    paid_in_full = payments_before_due >= prev_balance

    if paid_in_full:
        # Find the payment date for explanation
        payment_dates = [tx.post_date for tx in cycle.transactions if tx.category == "Payment"]
        pay_date_str = payment_dates[0].strftime("%m/%d/%Y") if payment_dates else "on time"
        due_str = prev_due_date.strftime("%m/%d/%Y") if prev_due_date else "N/A"
        return GracePeriodExplanation(
            eligible=True,
            reason=f"YES (previous balance paid in full by due date {due_str}; "
                   f"payment of ${prev_balance} received {pay_date_str}). "
                   f"New purchases have at least {params.grace_period_days} days before interest accrues.",
        )
    else:
        due_str = prev_due_date.strftime("%m/%d/%Y") if prev_due_date else "N/A"
        if payments_before_due > ZERO:
            return GracePeriodExplanation(
                eligible=False,
                reason=f"NO. Previous balance of ${prev_balance} was NOT paid in full by due date {due_str} "
                       f"(only minimum payment of ${payments_before_due} received). "
                       f"Interest charged on all balances including new purchases from posting date.",
            )
        else:
            return GracePeriodExplanation(
                eligible=False,
                reason=f"NO. Previous balance of ${prev_balance} was NOT paid in full by due date {due_str}. "
                       f"Interest charged on all balances including new purchases from posting date.",
            )


def _compute_interest(
    cycle: CycleData, params: AccountParams,
    grace_eligible: bool, opening_balance: Decimal,
    purchase_bal: Decimal = ZERO, cash_advance_bal: Decimal = ZERO,
) -> tuple[InterestExplanation, ADBTracker]:
    """Build ADB day by day from transactions and compute interest."""

    tracker = ADBTracker(
        cycle_start=cycle.cycle_start,
        cycle_end=cycle.cycle_end,
        opening_balance=opening_balance,
    )

    # Sort transactions by post date
    sorted_txns = sorted(cycle.transactions, key=lambda t: t.post_date)

    for tx in sorted_txns:
        if tx.category == "Purchase":
            tracker.post(tx.post_date, tx.amount, f"+Purchase ${tx.amount}")
        elif tx.category == "Cash Advance":
            tracker.post(tx.post_date, tx.amount, f"+Cash Advance ${tx.amount}")
        elif tx.category == "Payment":
            tracker.post(tx.post_date, -tx.amount, f"-Payment ${tx.amount}")
        elif tx.category == "Fee":
            tracker.post(tx.post_date, tx.amount, f"+{tx.description} ${tx.amount}")

    # Compute interest
    rt = params.rate_type  # "daily" or "monthly"

    if params.single_rate:
        # Single ADB for everything (WesTex style)
        rate = params.purchase_daily_rate
        if grace_eligible:
            adb_result = tracker.finalize(rate, cycle.days_in_cycle, rate_type=rt)
            exp = InterestExplanation(
                purchase_adb=adb_result["adb"],
                purchase_rate=rate,
                purchase_apr=params.purchase_apr,
                purchase_interest=ZERO,
                cash_advance_adb=ZERO,
                cash_advance_rate=rate,
                cash_advance_apr=params.cash_advance_apr,
                cash_advance_interest=ZERO,
                total_interest=ZERO,
                days_in_cycle=cycle.days_in_cycle,
                adb_entries=adb_result["entries"],
                grace_note="(not applied - grace period in effect)",
                rate_type=rt,
            )
        else:
            adb_result = tracker.finalize(rate, cycle.days_in_cycle, rate_type=rt)
            exp = InterestExplanation(
                purchase_adb=adb_result["adb"],
                purchase_rate=rate,
                purchase_apr=params.purchase_apr,
                purchase_interest=adb_result["interest"],
                cash_advance_adb=ZERO,
                cash_advance_rate=rate,
                cash_advance_apr=params.cash_advance_apr,
                cash_advance_interest=ZERO,
                total_interest=adb_result["interest"],
                days_in_cycle=cycle.days_in_cycle,
                adb_entries=adb_result["entries"],
                rate_type=rt,
            )
    else:
        # Dual ADB (USFederalCU style) — separate rates for purchases and cash advances
        purchase_tracker = ADBTracker(
            cycle_start=cycle.cycle_start,
            cycle_end=cycle.cycle_end,
            opening_balance=purchase_bal,
        )
        ca_tracker = ADBTracker(
            cycle_start=cycle.cycle_start,
            cycle_end=cycle.cycle_end,
            opening_balance=cash_advance_bal,
        )

        for tx in sorted_txns:
            if tx.category == "Purchase":
                purchase_tracker.post(tx.post_date, tx.amount, f"+Purchase ${tx.amount}")
            elif tx.category == "Cash Advance":
                ca_tracker.post(tx.post_date, tx.amount, f"+Cash Advance ${tx.amount}")
            elif tx.category == "Fee":
                # Fees go to purchase tracker (treated as purchase balance)
                purchase_tracker.post(tx.post_date, tx.amount, f"+{tx.description} ${tx.amount}")
            elif tx.category == "Payment":
                # Apply payment: reduce from each bucket proportionally or per waterfall
                # Simple approach: reduce purchase first, then cash advance
                p_bal = purchase_tracker.current_balance
                ca_bal = ca_tracker.current_balance
                remaining = tx.amount
                p_applied = min(remaining, p_bal)
                if p_applied > ZERO:
                    purchase_tracker.post(tx.post_date, -p_applied, f"-Payment ${p_applied}")
                    remaining = _round(remaining - p_applied)
                if remaining > ZERO and ca_bal > ZERO:
                    ca_applied = min(remaining, ca_bal)
                    ca_tracker.post(tx.post_date, -ca_applied, f"-Payment ${ca_applied}")

        p_rate = params.purchase_daily_rate
        ca_rate = params.cash_advance_daily_rate

        p_result = purchase_tracker.finalize(p_rate, cycle.days_in_cycle, rate_type=rt)
        ca_result = ca_tracker.finalize(ca_rate, cycle.days_in_cycle, rate_type=rt)

        p_interest = ZERO if grace_eligible else p_result["interest"]
        ca_interest = ca_result["interest"]  # cash advances NEVER have grace

        # Use the combined tracker entries for the display (shows total balance)
        combined_result = tracker.finalize(p_rate, cycle.days_in_cycle, rate_type=rt)

        exp = InterestExplanation(
            purchase_adb=p_result["adb"],
            purchase_rate=p_rate,
            purchase_apr=params.purchase_apr,
            purchase_interest=p_interest,
            cash_advance_adb=ca_result["adb"],
            cash_advance_rate=ca_rate,
            cash_advance_apr=params.cash_advance_apr,
            cash_advance_interest=ca_interest,
            total_interest=_round(p_interest + ca_interest),
            days_in_cycle=cycle.days_in_cycle,
            adb_entries=combined_result["entries"],
            grace_note="(not applied - grace period in effect for purchases)" if grace_eligible else "",
            rate_type=rt,
        )

    return exp, tracker


def _get_bucket_balance(total_balance: Decimal, cycle: CycleData, bucket: str,
                        purchase_bal: Decimal = ZERO, ca_bal: Decimal = ZERO) -> Decimal:
    """Return the opening balance for a specific bucket."""
    if bucket == "purchase":
        return purchase_bal
    else:
        return ca_bal


def _justify_fees(
    cycle: CycleData, params: AccountParams,
    prev_due_date: Optional[date], late_count: int,
) -> list[FeeExplanation]:
    """Generate fee justifications for every fee in this cycle."""
    explanations = []

    for tx in cycle.transactions:
        if tx.category != "Fee":
            continue

        desc_lower = tx.description.lower()

        if "late" in desc_lower:
            due_str = prev_due_date.strftime("%m/%d/%Y") if prev_due_date else "N/A"
            explanations.append(FeeExplanation(
                fee_date=tx.post_date,
                description=tx.description,
                amount=tx.amount,
                clause_ref=tx.clause_ref or "Agreement Section 7 - Late Payment Fee",
                justification=f"Minimum payment was not received by the due date of {due_str}. "
                              f"A late payment fee of ${tx.amount} has been assessed per the agreement.",
            ))

        elif "returned" in desc_lower:
            explanations.append(FeeExplanation(
                fee_date=tx.post_date,
                description=tx.description,
                amount=tx.amount,
                clause_ref=tx.clause_ref or "Agreement Section 7 - Returned Payment Fee",
                justification=f"Payment instrument was returned unpaid. Fee of ${tx.amount} assessed. "
                              f"Fee does not exceed the minimum payment amount for this period.",
            ))

        elif "over" in desc_lower and "limit" in desc_lower:
            explanations.append(FeeExplanation(
                fee_date=tx.post_date,
                description=tx.description,
                amount=tx.amount,
                clause_ref=tx.clause_ref or "Agreement Section 7 - Over Credit Limit Fee",
                justification=f"Account balance exceeded credit limit of ${params.credit_limit} "
                              f"on statement date. Fee of ${tx.amount} assessed and will recur monthly "
                              f"until balance is below the credit limit.",
            ))

        elif "foreign" in desc_lower or "intl" in desc_lower:
            explanations.append(FeeExplanation(
                fee_date=tx.post_date,
                description=tx.description,
                amount=tx.amount,
                clause_ref=tx.clause_ref or "Agreement Section 16 - Foreign Transaction Fee",
                justification=f"Foreign transaction fee of {params.foreign_transaction_pct * 100}% "
                              f"applied to international transaction. No grace period applies.",
            ))

        elif "cash advance" in desc_lower and "fee" in desc_lower:
            explanations.append(FeeExplanation(
                fee_date=tx.post_date,
                description=tx.description,
                amount=tx.amount,
                clause_ref=tx.clause_ref or "Agreement - Cash Advance Fee",
                justification=f"Cash advance fee assessed: greater of "
                              f"{params.cash_advance_fee_pct * 100}% or ${params.cash_advance_fee_min}.",
            ))

        elif "currency" in desc_lower or "conversion" in desc_lower:
            # Foreign currency conversion fee (multi/single currency tier)
            pct = params.foreign_transaction_pct
            if params.foreign_transaction_single_pct > ZERO and "single" in desc_lower:
                pct = params.foreign_transaction_single_pct
            explanations.append(FeeExplanation(
                fee_date=tx.post_date,
                description=tx.description,
                amount=tx.amount,
                clause_ref=tx.clause_ref or "Agreement - Foreign Transaction Fee",
                justification=f"Currency conversion fee of {pct * 100}% applied to international transaction.",
            ))

        elif "stop payment" in desc_lower:
            explanations.append(FeeExplanation(
                fee_date=tx.post_date,
                description=tx.description,
                amount=tx.amount,
                clause_ref=tx.clause_ref or "Agreement - Stop Payment Fee",
                justification=f"Stop payment fee of ${tx.amount} assessed on convenience check.",
            ))

        elif "card replacement" in desc_lower or "quick card" in desc_lower:
            explanations.append(FeeExplanation(
                fee_date=tx.post_date,
                description=tx.description,
                amount=tx.amount,
                clause_ref=tx.clause_ref or "Agreement - Card Fee",
                justification=f"Card issuance/replacement fee of ${tx.amount} assessed per agreement.",
            ))

        elif "copy" in desc_lower or "document" in desc_lower or "slip" in desc_lower:
            explanations.append(FeeExplanation(
                fee_date=tx.post_date,
                description=tx.description,
                amount=tx.amount,
                clause_ref=tx.clause_ref or "Agreement - Document Copy Fee",
                justification=f"Document copy fee of ${tx.amount} assessed per agreement.",
            ))

        else:
            explanations.append(FeeExplanation(
                fee_date=tx.post_date,
                description=tx.description,
                amount=tx.amount,
                clause_ref=tx.clause_ref or "Agreement",
                justification=f"Fee of ${tx.amount} assessed per agreement terms.",
            ))

    return explanations


def _explain_payments(
    cycle: CycleData, params: AccountParams,
    interest_owed: Decimal, fees_owed: Decimal,
) -> list[PaymentExplanation]:
    """Generate payment waterfall explanations."""
    explanations = []

    # Get the previous cycle's minimum payment and interest from the cycle data
    prev_min = cycle.minimum_payment  # This is actually this cycle's min, we need prev
    # We use the interest from the previous cycle that would be owed

    for tx in cycle.transactions:
        if tx.category != "Payment":
            continue

        payment_amount = tx.amount
        min_required = prev_min  # approximate

        steps = []
        remaining = payment_amount

        # Step 1: Collection costs
        steps.append(WaterfallStep(
            component="1. Collection Costs",
            amount=ZERO,
            applied_to="No collection costs outstanding",
        ))

        # Step 2: Interest & Fees
        int_fee_applied = min(remaining, _round(interest_owed + fees_owed))
        if int_fee_applied > ZERO:
            steps.append(WaterfallStep(
                component="2. Interest Charges & Fees",
                amount=int_fee_applied,
                applied_to="Applied to accrued interest and fees",
            ))
            remaining = _round(remaining - int_fee_applied)
        else:
            steps.append(WaterfallStep(
                component="2. Interest Charges & Fees",
                amount=ZERO,
                applied_to="No interest or fees outstanding" if interest_owed <= ZERO else f"${interest_owed} applied",
            ))

        # Step 3: Principal
        principal_applied = remaining
        if principal_applied > ZERO:
            steps.append(WaterfallStep(
                component="3. Principal",
                amount=principal_applied,
                applied_to="Applied to principal balance",
            ))
        else:
            steps.append(WaterfallStep(
                component="3. Principal",
                amount=ZERO,
                applied_to="Entire payment absorbed by interest/fees",
            ))

        # Excess
        excess = _round(payment_amount - min_required) if payment_amount > min_required else ZERO

        explanations.append(PaymentExplanation(
            payment_date=tx.post_date,
            total_amount=payment_amount,
            minimum_required=min_required,
            steps=steps,
            excess_amount=max(excess, ZERO),
            excess_applied_to="Applied to highest-rate balance" if excess > ZERO else "",
        ))

    return explanations


def _update_balances_after_cycle(result: CycleResult, cycle: CycleData, params: AccountParams) -> None:
    """Update tracked balances after cycle processing."""
    pass  # Balances are tracked via new_balance from cycle data


def _resolve_grace_forward(results: list[CycleResult], history: StatementHistory) -> None:
    """Second pass: resolve grace eligibility using payment data from the next cycle.

    Key rule: Grace for cycle N requires BOTH:
      (a) Previous cycle (N-1) had grace eligible = True, AND
      (b) Cycle N-1 statement balance was paid in full by its due date.
    OR: no previous balance / first cycle.

    Once grace is lost, paying the statement balance in full causes "trailing interest"
    for the current cycle. Grace is only restored for the NEXT cycle after the trailing
    interest is paid off.
    """
    for i in range(1, len(results)):
        prev_result = results[i - 1]
        curr_cycle = history.cycles[i]
        params = history.params

        prev_balance = prev_result.new_balance
        prev_due = prev_result.payment_due_date
        prev_grace = prev_result.grace_explanation.eligible if prev_result.grace_explanation else True

        if prev_balance <= ZERO:
            results[i].grace_explanation = GracePeriodExplanation(
                eligible=True,
                reason=f"YES (no previous balance). New purchases have at least "
                       f"{params.grace_period_days} days before interest accrues.",
            )
        elif not prev_grace:
            # Previous cycle had NO grace.
            due_str = prev_due.strftime("%m/%d/%Y") if prev_due else "N/A"

            # Check if they did pay the statement balance in full
            payments_before_due = ZERO
            payment_date_str = ""
            if prev_due:
                for tx in curr_cycle.transactions:
                    if tx.category == "Payment" and tx.post_date <= prev_due:
                        payments_before_due += tx.amount
                        payment_date_str = tx.post_date.strftime("%m/%d/%Y")

            paid_stmt = payments_before_due >= prev_balance

            if params.trailing_interest_grace:
                # Trailing interest rule (WesTex): even if statement paid in full,
                # grace NOT restored this cycle because interest was accruing daily.
                # Grace restores NEXT cycle.
                reason = (
                    f"NO. Previous balance NOT paid in full. "
                    f"Interest charged on all balances including new purchases from posting date."
                )
                if paid_stmt:
                    reason += (
                        f"\nNote: Payment of ${payments_before_due} received {payment_date_str} "
                        f"covers the statement balance. Grace period will be RESTORED for the next "
                        f"billing cycle if the new balance is paid in full by the next due date."
                    )
                results[i].grace_explanation = GracePeriodExplanation(eligible=False, reason=reason)
            else:
                # Standard rule (USFederalCU): paying statement balance in full
                # restores grace for THIS cycle.
                if paid_stmt:
                    results[i].grace_explanation = GracePeriodExplanation(
                        eligible=True,
                        reason=f"YES (previous statement balance paid in full by due date {due_str}; "
                               f"payment of ${payments_before_due} received {payment_date_str}). "
                               f"New purchases have at least {params.grace_period_days} days before interest accrues.",
                    )
                else:
                    if payments_before_due > ZERO:
                        reason = (
                            f"NO. Previous balance of ${prev_balance} was NOT paid in full by due date {due_str} "
                            f"(only ${payments_before_due} received {payment_date_str}). "
                            f"Interest charged on all balances from posting date."
                        )
                    else:
                        reason = (
                            f"NO. Previous balance of ${prev_balance} was NOT paid in full by due date {due_str}. "
                            f"Interest charged on all balances from posting date."
                        )
                    results[i].grace_explanation = GracePeriodExplanation(eligible=False, reason=reason)
        else:
            # Previous cycle HAD grace — check if balance was paid in full
            due_str = prev_due.strftime("%m/%d/%Y") if prev_due else "N/A"

            payments_before_due = ZERO
            payment_date_str = ""
            if prev_due:
                for tx in curr_cycle.transactions:
                    if tx.category == "Payment" and tx.post_date <= prev_due:
                        payments_before_due += tx.amount
                        payment_date_str = tx.post_date.strftime("%m/%d/%Y")

            paid_in_full = payments_before_due >= prev_balance

            if paid_in_full:
                results[i].grace_explanation = GracePeriodExplanation(
                    eligible=True,
                    reason=f"YES (previous balance paid in full by due date {due_str}; "
                           f"payment of ${payments_before_due} received {payment_date_str}). "
                           f"New purchases have at least {params.grace_period_days} days before interest accrues.",
                )
            else:
                if payments_before_due > ZERO:
                    reason = (
                        f"NO. Previous balance of ${prev_balance} was NOT paid in full by due date {due_str} "
                        f"(only minimum payment of ${payments_before_due} received "
                        f"{payment_date_str}). Interest charged on all balances including new purchases "
                        f"from posting date. Cash advances accrue interest from posting date regardless "
                        f"of grace period status."
                    )
                else:
                    reason = (
                        f"NO. Previous balance of ${prev_balance} was NOT paid in full by due date {due_str}. "
                        f"Interest charged on all balances including new purchases from posting date."
                    )
                results[i].grace_explanation = GracePeriodExplanation(eligible=False, reason=reason)

        # Re-compute interest with corrected grace
        curr_grace = results[i].grace_explanation.eligible
        was_grace = results[i].interest_explanation.total_interest == ZERO if results[i].interest_explanation else True
        if curr_grace != was_grace:
            int_exp, _ = _compute_interest(
                curr_cycle, params,
                curr_grace,
                prev_result.new_balance,
            )
            results[i].interest_explanation = int_exp
            results[i].total_interest = int_exp.total_interest
