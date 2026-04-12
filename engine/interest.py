"""Interest calculation: Average Daily Balance method per Section 6."""

from decimal import Decimal

from engine.account import Account, Statement, to_cents, ZERO


def evaluate_grace_period(account: Account) -> bool:
    """Determine if grace period is eligible for the upcoming cycle.

    Section 6: Grace applies if previous balance was paid in full by due date,
    or there was no previous balance.
    """
    if account.last_statement is None:
        # First cycle — no previous balance
        return True

    prev = account.last_statement
    if prev.new_balance <= ZERO:
        # No previous balance
        return True

    # Was previous statement paid in full by its due date?
    # The simulator tracks this via account.payments_this_cycle vs prev.new_balance
    # By the time we evaluate, the cycle has ended and we check if cumulative
    # payments (before due date) covered the statement balance.
    # This is set by the simulator before calling cycle_end.
    return prev.new_balance <= ZERO  # already checked above; actual check is in simulator


def compute_cycle_interest(account: Account, days_in_cycle: int, current_day: int) -> dict:
    """Compute interest for each bucket at cycle end.

    Returns dict with per-bucket and total interest.
    """
    result = {
        "purchase_interest": ZERO,
        "cash_advance_interest": ZERO,
        "balance_transfer_interest": ZERO,
        "total_interest": ZERO,
    }

    # Purchases: interest only if grace is NOT eligible
    if account.grace_period_eligible:
        result["purchase_interest"] = ZERO
    else:
        result["purchase_interest"] = account.purchases.compute_interest(
            days_in_cycle, current_day)

    # Cash advances: always accrue interest (no grace period ever)
    result["cash_advance_interest"] = account.cash_advances.compute_interest(
        days_in_cycle, current_day)

    # Balance transfers: treated as cash advances for grace purposes (no grace)
    result["balance_transfer_interest"] = account.balance_transfers.compute_interest(
        days_in_cycle, current_day)

    result["total_interest"] = to_cents(
        result["purchase_interest"]
        + result["cash_advance_interest"]
        + result["balance_transfer_interest"]
    )

    return result
