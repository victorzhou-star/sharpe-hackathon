"""Fee assessment logic per Section 7 and Section 14."""

from decimal import Decimal

from engine.account import Account, to_cents, ZERO


def assess_late_payment_fee(account: Account) -> Decimal:
    """$25 if payment not received by due date. Section 7."""
    fee = Decimal("25.00")
    account.fees_balance = to_cents(account.fees_balance + fee)
    account.add_log(0, "FEE_LATE_PAYMENT", amount=str(fee))
    return fee


def assess_returned_payment_fee(account: Account, min_payment: Decimal) -> Decimal:
    """$25 per returned item, capped at minimum payment for the period. Section 7."""
    fee = Decimal("25.00")
    # Cap: "In no event will the Returned Payment Fee exceed the minimum payment amount"
    fee = min(fee, min_payment) if min_payment > ZERO else fee
    account.fees_balance = to_cents(account.fees_balance + fee)
    account.add_log(0, "FEE_RETURNED_PAYMENT", amount=str(fee))
    return fee


def assess_over_limit_fee(account: Account, new_balance_less_fees: Decimal) -> Decimal:
    """$10 if new balance (less fees this cycle) exceeds credit limit. Section 7.
    Recurring each month until below limit."""
    if new_balance_less_fees > account.credit_limit:
        fee = Decimal("10.00")
        account.fees_balance = to_cents(account.fees_balance + fee)
        account.add_log(0, "FEE_OVER_LIMIT", amount=str(fee),
                        balance=str(new_balance_less_fees),
                        limit=str(account.credit_limit))
        return fee
    return ZERO


def assess_foreign_transaction_fee(account: Account, tx_amount: Decimal) -> Decimal:
    """Up to 1% of transaction amount. Section 16. No grace period."""
    fee = to_cents(tx_amount * Decimal("0.01"))
    if fee > ZERO:
        account.fees_balance = to_cents(account.fees_balance + fee)
        account.add_log(0, "FEE_FOREIGN_TRANSACTION", amount=str(fee))
    return fee


def assess_atm_operator_fee(account: Account, fee_amount: Decimal) -> Decimal:
    """Passthrough from ATM operator. Treated as purchase. Section 7."""
    if fee_amount > ZERO:
        # Treated as purchase per contract
        account.purchases.post_charge(fee_amount)
        account.add_log(0, "FEE_ATM_OPERATOR", amount=str(fee_amount))
    return fee_amount


def assess_card_replacement_fee(account: Account) -> Decimal:
    """$5 per replacement card. Section 7."""
    fee = Decimal("5.00")
    account.fees_balance = to_cents(account.fees_balance + fee)
    account.add_log(0, "FEE_CARD_REPLACEMENT", amount=str(fee))
    return fee


def assess_document_copy_fee(account: Account, is_cu_error_context: bool) -> Decimal:
    """$2 per copy. Waived if CU billing error context. Section 7."""
    if is_cu_error_context:
        return ZERO
    fee = Decimal("2.00")
    account.fees_balance = to_cents(account.fees_balance + fee)
    account.add_log(0, "FEE_DOCUMENT_COPY", amount=str(fee))
    return fee


def assess_convenience_check_copy_fee(account: Account) -> Decimal:
    """$2 for copy of paid convenience check. Section 14."""
    fee = Decimal("2.00")
    account.fees_balance = to_cents(account.fees_balance + fee)
    return fee


def assess_convenience_check_stop_fee(account: Account) -> Decimal:
    """$20 stop payment on convenience check. Section 14."""
    fee = Decimal("20.00")
    account.fees_balance = to_cents(account.fees_balance + fee)
    return fee


def assess_convenience_check_nsf_fee(account: Account) -> Decimal:
    """$25 NSF on convenience check. Section 14."""
    fee = Decimal("25.00")
    account.fees_balance = to_cents(account.fees_balance + fee)
    return fee
