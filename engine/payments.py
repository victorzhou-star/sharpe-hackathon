"""Payment processing: waterfall allocation and minimum payment calculation per Sections 5, 10."""

from decimal import Decimal

from engine.account import Account, to_cents, ZERO, CENT


def compute_minimum_payment(new_balance: Decimal) -> Decimal:
    """Compute minimum payment per Section 5.

    - 3% of new balance or $15, whichever is greater
    - If balance <= $15, pay in full
    - If balance is $0, minimum is $0
    """
    if new_balance <= ZERO:
        return ZERO

    threshold = Decimal("15.00")
    if new_balance <= threshold:
        return to_cents(new_balance)

    pct = to_cents(new_balance * Decimal("0.03"))
    return max(pct, threshold)


def apply_payment(account: Account, amount: Decimal) -> dict:
    """Apply a payment using the waterfall from Section 10.

    Minimum payment applied:
      1. Collection costs
      2. Interest and fees
      3. Principal (lowest rate bucket)

    Excess above minimum:
      Applied to highest rate bucket first.

    Returns a breakdown dict.
    """
    remaining = amount
    breakdown = {
        "total": amount,
        "to_collection_costs": ZERO,
        "to_interest": ZERO,
        "to_fees": ZERO,
        "to_principal": {},  # bucket_name -> amount
        "applied": ZERO,
    }

    min_payment = ZERO
    if account.last_statement:
        min_payment = account.last_statement.minimum_payment
    if min_payment <= ZERO:
        min_payment = compute_minimum_payment(account.total_balance)

    # ---------------------------------------------------------------
    # Phase 1: Apply minimum payment per waterfall
    # ---------------------------------------------------------------
    min_to_apply = min(remaining, min_payment)

    # 1. Collection costs
    if account.collection_costs > ZERO and min_to_apply > ZERO:
        applied = min(min_to_apply, account.collection_costs)
        account.collection_costs = to_cents(account.collection_costs - applied)
        breakdown["to_collection_costs"] = applied
        min_to_apply = to_cents(min_to_apply - applied)
        remaining = to_cents(remaining - applied)

    # 2. Interest and fees
    interest_and_fees = to_cents(account.interest_balance + account.fees_balance)
    if interest_and_fees > ZERO and min_to_apply > ZERO:
        applied = min(min_to_apply, interest_and_fees)

        # Split proportionally between interest and fees
        if account.interest_balance > ZERO:
            int_applied = min(applied, account.interest_balance)
            account.interest_balance = to_cents(account.interest_balance - int_applied)
            breakdown["to_interest"] = int_applied
            applied_remaining = to_cents(applied - int_applied)
        else:
            applied_remaining = applied

        if applied_remaining > ZERO and account.fees_balance > ZERO:
            fee_applied = min(applied_remaining, account.fees_balance)
            account.fees_balance = to_cents(account.fees_balance - fee_applied)
            breakdown["to_fees"] = fee_applied

        min_to_apply = to_cents(min_to_apply - applied)
        remaining = to_cents(remaining - applied)

    # 3. Principal — lowest rate bucket first (for minimum payment portion)
    if min_to_apply > ZERO:
        for bucket in account.buckets_by_rate_ascending():
            if bucket.balance > ZERO and min_to_apply > ZERO:
                applied = min(min_to_apply, bucket.balance)
                bucket.apply_payment(applied)
                breakdown["to_principal"][bucket.name] = (
                    breakdown["to_principal"].get(bucket.name, ZERO) + applied
                )
                min_to_apply = to_cents(min_to_apply - applied)
                remaining = to_cents(remaining - applied)

    # ---------------------------------------------------------------
    # Phase 2: Excess above minimum — highest rate first
    # ---------------------------------------------------------------
    if remaining > ZERO:
        # First clear any remaining interest/fees
        if account.interest_balance > ZERO:
            applied = min(remaining, account.interest_balance)
            account.interest_balance = to_cents(account.interest_balance - applied)
            breakdown["to_interest"] = to_cents(breakdown["to_interest"] + applied)
            remaining = to_cents(remaining - applied)

        if remaining > ZERO and account.fees_balance > ZERO:
            applied = min(remaining, account.fees_balance)
            account.fees_balance = to_cents(account.fees_balance - applied)
            breakdown["to_fees"] = to_cents(breakdown["to_fees"] + applied)
            remaining = to_cents(remaining - applied)

        # Then principal — highest rate first
        for bucket in account.buckets_by_rate_descending():
            if bucket.balance > ZERO and remaining > ZERO:
                applied = min(remaining, bucket.balance)
                bucket.apply_payment(applied)
                breakdown["to_principal"][bucket.name] = (
                    breakdown["to_principal"].get(bucket.name, ZERO) + applied
                )
                remaining = to_cents(remaining - applied)

    breakdown["applied"] = to_cents(amount - remaining)
    return breakdown
