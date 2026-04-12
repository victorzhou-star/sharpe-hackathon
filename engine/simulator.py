"""Main simulation engine: day-tick loop with event queue."""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from engine.account import (
    Account, BalanceBucket, Statement, Dispute, UnauthorizedUseRecord,
    LiabilityRecord, to_cents, ZERO,
)
from engine.events import (
    Event, AccountStatus, DisputeStatus, DefaultCode,
    AccountOpened, AuthorizedUserAdded, AuthorizedUserRevoked,
    JointApplicantWithdrawal, CreditLimitChanged,
    AccountTerminatedByCU, AccountTerminatedByCardholder,
    CardIssued, SkipPaymentOffered, AccountSuspended,
    Purchase, CashAdvanceATM, CashAdvanceOther, BalanceTransfer,
    ConvenienceCheckUsed, IllegalTransaction, MerchantCredit,
    PaymentReceived, PaymentReturned, CycleEnd,
    BillingErrorClaimed, DisputeAcknowledged, DisputeResolvedInFavor,
    DisputeResolvedAgainst, CardholderRejectsResolution, PurchaseDisputeFiled,
    UnauthorizedUse, UnauthorizedUseReported, GrossNegligenceFlagged,
    TermsChanged, AddressChanged, CreditInsurancePurchased,
    DocumentCopyRequested, ConvenienceCheckCopyRequested,
    ConvenienceCheckStopRequested,
    CardholderBankruptcyFiled, LegalGarnishmentAttempted,
    FalseInfoDiscovered, RepaymentAbilityEndangered,
    CardSurrenderDemanded, SecurityInterestEnforced, CollectionInitiated,
)
from engine.interest import compute_cycle_interest
from engine.payments import apply_payment, compute_minimum_payment
from engine import fees as fee_engine


def simulate(events: list[Event], ir: Optional[dict] = None) -> Account:
    """Run the simulation given a list of injected events.

    Args:
        events: List of Event objects (injected by the judge/scenario).
        ir: Optional IR dict for configuration overrides.

    Returns:
        The final Account state with full execution log and statements.
    """
    account = Account()

    # Sort events: by day, then by priority within same day
    sorted_events = sorted(events, key=lambda e: (e.day, e.priority))

    # Find the last day we need to simulate
    last_day = max(e.day for e in sorted_events) if sorted_events else 1

    # Index events by day for quick lookup
    events_by_day: dict[int, list[Event]] = {}
    for ev in sorted_events:
        events_by_day.setdefault(ev.day, []).append(ev)

    # Track payments received between statement due dates
    # Key: cycle_number -> total payments received before due date
    payments_by_due_date: dict[int, Decimal] = {}
    current_due_day: Optional[int] = None
    current_statement_balance: Decimal = ZERO

    # Day-tick loop
    for day in range(1, last_day + 1):
        day_events = events_by_day.get(day, [])

        for event in day_events:
            _process_event(account, event, day, payments_by_due_date)

        # After processing events, take daily balance snapshot
        # (skip if CycleEnd already did it to avoid double-counting)
        if account.cardholder_name and not getattr(account, '_cycle_end_snapshotted', False):
            account.snapshot_daily_balances()
        account._cycle_end_snapshotted = False

    return account


def _process_event(account: Account, event: Event, day: int,
                   payments_by_due_date: dict[int, Decimal]) -> None:
    """Dispatch a single event to its handler."""

    # ---------------------------------------------------------------
    # Account Lifecycle
    # ---------------------------------------------------------------
    if isinstance(event, AccountOpened):
        _handle_account_opened(account, event, day)

    elif isinstance(event, AuthorizedUserAdded):
        account.authorized_users.append(event.user_name)
        account.add_log(day, "AUTHORIZED_USER_ADDED", user=event.user_name)

    elif isinstance(event, AuthorizedUserRevoked):
        effective = event.card_returned and event.written_notice
        account.add_log(day, "AUTHORIZED_USER_REVOKED",
                        user=event.user_name, effective=effective)
        if effective and event.user_name in account.authorized_users:
            account.authorized_users.remove(event.user_name)

    elif isinstance(event, JointApplicantWithdrawal):
        if event.written_notice:
            account.liability_records.append(LiabilityRecord(
                party=event.applicant_name,
                liable_for_charges_before=day,
                withdrawn_day=day,
            ))
            account.add_log(day, "JOINT_WITHDRAWAL",
                            applicant=event.applicant_name, effective=True)
        else:
            account.add_log(day, "JOINT_WITHDRAWAL",
                            applicant=event.applicant_name, effective=False)

    elif isinstance(event, CreditLimitChanged):
        old = account.credit_limit
        account.credit_limit = event.new_limit
        account.add_log(day, "CREDIT_LIMIT_CHANGED",
                        old=str(old), new=str(event.new_limit))

    elif isinstance(event, AccountTerminatedByCU):
        account.status = AccountStatus.TERMINATED
        account.add_log(day, "TERMINATED_BY_CU")

    elif isinstance(event, AccountTerminatedByCardholder):
        account.status = AccountStatus.TERMINATED
        account.add_log(day, "TERMINATED_BY_CARDHOLDER")

    elif isinstance(event, CardIssued):
        if event.is_replacement:
            fee_engine.assess_card_replacement_fee(account)
        account.add_log(day, "CARD_ISSUED",
                        recipient=event.recipient, replacement=event.is_replacement)

    elif isinstance(event, SkipPaymentOffered):
        account.skip_payment_cycle = event.cycle_to_skip
        account.add_log(day, "SKIP_PAYMENT_OFFERED", cycle=event.cycle_to_skip)

    elif isinstance(event, AccountSuspended):
        account.status = AccountStatus.SUSPENDED
        account.add_log(day, "ACCOUNT_SUSPENDED", reason=event.reason)

    # ---------------------------------------------------------------
    # Transactions
    # ---------------------------------------------------------------
    elif isinstance(event, Purchase):
        _handle_purchase(account, event, day)

    elif isinstance(event, CashAdvanceATM):
        _handle_cash_advance_atm(account, event, day)

    elif isinstance(event, CashAdvanceOther):
        account.cash_advances.post_charge(event.amount)
        account.add_log(day, "CASH_ADVANCE", amount=str(event.amount))
        if event.is_international:
            fee_engine.assess_foreign_transaction_fee(account, event.amount)

    elif isinstance(event, BalanceTransfer):
        account.balance_transfers.post_charge(event.amount)
        account.add_log(day, "BALANCE_TRANSFER", amount=str(event.amount),
                        from_inst=event.from_institution)

    elif isinstance(event, ConvenienceCheckUsed):
        # Posted as cash advance
        account.cash_advances.post_charge(event.amount)
        account.add_log(day, "CONVENIENCE_CHECK", amount=str(event.amount))

    elif isinstance(event, IllegalTransaction):
        account.purchases.post_charge(event.amount)
        _trigger_default(account, day, DefaultCode.D2, "illegal_transaction")
        account.add_log(day, "ILLEGAL_TRANSACTION", amount=str(event.amount))

    elif isinstance(event, MerchantCredit):
        # Reduce purchase balance
        account.purchases.apply_payment(event.amount)
        account.add_log(day, "MERCHANT_CREDIT", amount=str(event.amount))

    # ---------------------------------------------------------------
    # Payments
    # ---------------------------------------------------------------
    elif isinstance(event, PaymentReceived):
        _handle_payment(account, event, day, payments_by_due_date)

    elif isinstance(event, PaymentReturned):
        _handle_payment_returned(account, event, day)

    # ---------------------------------------------------------------
    # Cycle End
    # ---------------------------------------------------------------
    elif isinstance(event, CycleEnd):
        _handle_cycle_end(account, event, day, payments_by_due_date)

    # ---------------------------------------------------------------
    # Disputes
    # ---------------------------------------------------------------
    elif isinstance(event, BillingErrorClaimed):
        _handle_billing_error(account, event, day)

    elif isinstance(event, DisputeAcknowledged):
        _handle_dispute_ack(account, event, day)

    elif isinstance(event, DisputeResolvedInFavor):
        _handle_dispute_resolved_favor(account, event, day)

    elif isinstance(event, DisputeResolvedAgainst):
        _handle_dispute_resolved_against(account, event, day)

    elif isinstance(event, CardholderRejectsResolution):
        _handle_cardholder_rejects(account, event, day)

    elif isinstance(event, PurchaseDisputeFiled):
        _handle_purchase_dispute(account, event, day)

    # ---------------------------------------------------------------
    # Unauthorized Use
    # ---------------------------------------------------------------
    elif isinstance(event, UnauthorizedUse):
        record = UnauthorizedUseRecord(
            day=day, amount=event.amount, tx_type=event.tx_type)
        account.unauthorized_uses.append(record)
        account.add_log(day, "UNAUTHORIZED_USE",
                        amount=str(event.amount), type=event.tx_type)

    elif isinstance(event, UnauthorizedUseReported):
        _handle_unauthorized_reported(account, event, day)

    elif isinstance(event, GrossNegligenceFlagged):
        for rec in account.unauthorized_uses:
            if not rec.reported:
                rec.gross_negligence = True
        account.add_log(day, "GROSS_NEGLIGENCE_FLAGGED")

    # ---------------------------------------------------------------
    # Default triggers (injected)
    # ---------------------------------------------------------------
    elif isinstance(event, CardholderBankruptcyFiled):
        _trigger_default(account, day, DefaultCode.D3, "bankruptcy")

    elif isinstance(event, LegalGarnishmentAttempted):
        _trigger_default(account, day, DefaultCode.D4, "garnishment")

    elif isinstance(event, FalseInfoDiscovered):
        _trigger_default(account, day, DefaultCode.D5, event.what_was_false)

    elif isinstance(event, RepaymentAbilityEndangered):
        _trigger_default(account, day, DefaultCode.D6, event.reason)

    elif isinstance(event, CollectionInitiated):
        total = to_cents(event.attorney_fees + event.court_costs + event.recovery_costs)
        account.collection_costs = to_cents(account.collection_costs + total)
        account.add_log(day, "COLLECTION_INITIATED", total=str(total))

    # ---------------------------------------------------------------
    # Admin
    # ---------------------------------------------------------------
    elif isinstance(event, TermsChanged):
        account.terms_changed_day = day
        account.add_log(day, "TERMS_CHANGED", changes=event.changes)

    elif isinstance(event, AddressChanged):
        account.home_address = event.new_address
        account.home_state = event.new_state
        account.add_log(day, "ADDRESS_CHANGED", new_state=event.new_state)

    elif isinstance(event, CreditInsurancePurchased):
        account.purchases.post_charge(event.premium_amount)
        account.add_log(day, "CREDIT_INSURANCE", amount=str(event.premium_amount))

    elif isinstance(event, DocumentCopyRequested):
        fee_engine.assess_document_copy_fee(account, event.is_cu_error_context)

    elif isinstance(event, ConvenienceCheckCopyRequested):
        fee_engine.assess_convenience_check_copy_fee(account)

    elif isinstance(event, ConvenienceCheckStopRequested):
        fee_engine.assess_convenience_check_stop_fee(account)


# ===================================================================
# Event Handlers
# ===================================================================

def _handle_account_opened(account: Account, event: AccountOpened, day: int) -> None:
    account.cardholder_name = event.cardholder_name
    account.credit_limit = event.credit_limit
    account.card_product = event.card_product
    account.is_joint = event.is_joint
    account.joint_applicant_name = event.joint_applicant_name
    account.home_state = event.home_state
    account.home_address = event.home_address
    account.grace_period_eligible = True
    account.status = AccountStatus.ACTIVE
    account.cycle_start_day = day

    # Set APRs based on event
    apr_p = event.apr_purchase
    apr_ca = event.apr_cash_advance

    # Look up daily rate from the contract's defined rates
    account.purchases = BalanceBucket(
        name="purchases",
        apr=apr_p,
        daily_rate=_apr_to_daily_rate(apr_p),
    )
    account.cash_advances = BalanceBucket(
        name="cash_advances",
        apr=apr_ca,
        daily_rate=_apr_to_daily_rate(apr_ca),
    )

    # Balance transfers — use post-intro rate from product
    bt_apr = Decimal("8.9")  # default for Platinum
    account.balance_transfers = BalanceBucket(
        name="balance_transfers",
        apr=bt_apr,
        daily_rate=_apr_to_daily_rate(bt_apr),
        intro_rate=Decimal("0"),
        intro_expires_day=day + 180,  # 6 months
    )

    account.add_log(day, "ACCOUNT_OPENED",
                    cardholder=event.cardholder_name,
                    limit=str(event.credit_limit),
                    apr_purchase=str(apr_p),
                    apr_cash_advance=str(apr_ca))


def _apr_to_daily_rate(apr: Decimal) -> Decimal:
    """Map APR to the contract's exact daily periodic rate."""
    rates = {
        Decimal("4.9"): Decimal("0.00013425"),   # 4.9/365
        Decimal("6.9"): Decimal("0.00018904"),
        Decimal("7.9"): Decimal("0.00021644"),
        Decimal("8.9"): Decimal("0.00024383"),
        Decimal("10.9"): Decimal("0.0002986"),
        Decimal("12.9"): Decimal("0.0003534"),
        Decimal("15.9"): Decimal("0.00043562"),
    }
    if apr in rates:
        return rates[apr]
    # Fallback: compute from APR
    return (apr / Decimal("100") / Decimal("365")).quantize(
        Decimal("0.0000000001"))


def _handle_purchase(account: Account, event: Purchase, day: int) -> None:
    account.purchases.post_charge(event.amount)
    account.add_log(day, "PURCHASE", amount=str(event.amount),
                    merchant=event.merchant_name)

    if event.is_international:
        fee_engine.assess_foreign_transaction_fee(account, event.amount)


def _handle_cash_advance_atm(account: Account, event: CashAdvanceATM, day: int) -> None:
    account.cash_advances.post_charge(event.amount)
    account.add_log(day, "CASH_ADVANCE_ATM", amount=str(event.amount))

    if event.atm_operator_fee > ZERO:
        fee_engine.assess_atm_operator_fee(account, event.atm_operator_fee)

    if event.is_international:
        fee_engine.assess_foreign_transaction_fee(account, event.amount)


def _handle_payment(account: Account, event: PaymentReceived, day: int,
                    payments_by_due_date: dict[int, Decimal]) -> None:
    breakdown = apply_payment(account, event.amount)
    account.payments_this_cycle = to_cents(account.payments_this_cycle + event.amount)

    # Track payments against current due date for grace period evaluation
    if account.last_statement:
        cycle_num = account.last_statement.cycle_number
        current = payments_by_due_date.get(cycle_num, ZERO)
        payments_by_due_date[cycle_num] = to_cents(current + event.amount)

    account.add_log(day, "PAYMENT_RECEIVED",
                    amount=str(event.amount),
                    breakdown={k: str(v) if isinstance(v, Decimal) else
                               {bk: str(bv) for bk, bv in v.items()} if isinstance(v, dict) else v
                               for k, v in breakdown.items()})


def _handle_payment_returned(account: Account, event: PaymentReturned, day: int) -> None:
    # Reverse the payment credit — add amount back to purchase bucket
    account.purchases.post_charge(event.amount)
    account.payments_this_cycle = to_cents(
        account.payments_this_cycle - event.amount)

    # Also reverse from tracking
    if account.last_statement:
        cycle_num = account.last_statement.cycle_number
        # We don't have payments_by_due_date here, but the simulator
        # handles this via the payment_returned_this_cycle flag
    account.payment_returned_this_cycle = True

    # Assess returned payment fee
    min_payment = ZERO
    if account.last_statement:
        min_payment = account.last_statement.minimum_payment
    fee_engine.assess_returned_payment_fee(account, min_payment)

    account.add_log(day, "PAYMENT_RETURNED", amount=str(event.amount))


def _handle_cycle_end(account: Account, event: CycleEnd, day: int,
                      payments_by_due_date: dict[int, Decimal]) -> None:
    cycle_num = event.cycle_number if event.cycle_number > 0 else account.cycle_number + 1
    account.cycle_number = cycle_num

    days_in_cycle = day - account.cycle_start_day + 1

    # ---------------------------------------------------------------
    # 1. Evaluate grace period for this cycle
    # ---------------------------------------------------------------
    if account.last_statement is None:
        # First cycle: no previous balance
        account.grace_period_eligible = True
    else:
        prev = account.last_statement
        prev_cycle = prev.cycle_number
        paid = payments_by_due_date.get(prev_cycle, ZERO)
        account.grace_period_eligible = (paid >= prev.new_balance)

    # ---------------------------------------------------------------
    # 1b. Snapshot today's balance BEFORE computing interest
    #     (so cycle-end day is included in ADB calculation)
    # ---------------------------------------------------------------
    account.snapshot_daily_balances()
    account._cycle_end_snapshotted = True  # flag to skip duplicate in main loop

    # ---------------------------------------------------------------
    # 2. Compute interest
    # ---------------------------------------------------------------
    interest_result = compute_cycle_interest(account, days_in_cycle, day)
    account.interest_balance = to_cents(
        account.interest_balance + interest_result["total_interest"])

    # ---------------------------------------------------------------
    # 3. Compute new balance and fees
    # ---------------------------------------------------------------
    # Track cycle totals for statement
    cycle_purchases = ZERO
    cycle_cash_advances = ZERO
    cycle_bt = ZERO
    cycle_payments = account.payments_this_cycle
    cycle_fees = ZERO

    # Calculate new balance components
    prev_balance = ZERO
    if account.last_statement:
        prev_balance = account.last_statement.new_balance

    new_balance = account.total_balance

    # ---------------------------------------------------------------
    # 4. Check late payment (was min payment met by due date?)
    # ---------------------------------------------------------------
    late_fee = ZERO
    if account.last_statement:
        prev = account.last_statement
        paid_by_due = payments_by_due_date.get(prev.cycle_number, ZERO)
        is_skip_cycle = (account.skip_payment_cycle == cycle_num)

        if not is_skip_cycle and paid_by_due < prev.minimum_payment and prev.minimum_payment > ZERO:
            late_fee = fee_engine.assess_late_payment_fee(account)
            _trigger_default(account, day, DefaultCode.D1, "missed_payment")
            new_balance = account.total_balance

    # ---------------------------------------------------------------
    # 5. Check over-limit
    # ---------------------------------------------------------------
    over_limit_fee = ZERO
    # "new balance, less any fees imposed during the cycle"
    balance_less_fees = to_cents(new_balance - late_fee - account.fees_balance + account.fees_balance)
    # Simplification: check principal + interest vs limit
    balance_for_overlimit = to_cents(
        account.purchases.balance + account.cash_advances.balance
        + account.balance_transfers.balance + account.interest_balance)
    if balance_for_overlimit > account.credit_limit:
        over_limit_fee = fee_engine.assess_over_limit_fee(account, balance_for_overlimit)
        new_balance = account.total_balance

    # ---------------------------------------------------------------
    # 6. Generate statement
    # ---------------------------------------------------------------
    new_balance = account.total_balance
    min_payment = compute_minimum_payment(new_balance)
    due_day = day + 25

    stmt = Statement(
        cycle_number=cycle_num,
        cycle_start_day=account.cycle_start_day,
        cycle_end_day=day,
        previous_balance=prev_balance,
        total_interest=interest_result["total_interest"],
        purchase_interest=interest_result["purchase_interest"],
        cash_advance_interest=interest_result["cash_advance_interest"],
        balance_transfer_interest=interest_result["balance_transfer_interest"],
        total_payments=cycle_payments,
        new_balance=new_balance,
        minimum_payment=min_payment,
        payment_due_day=due_day,
        grace_period_eligible=account.grace_period_eligible,
        late_fee=late_fee,
        over_limit_fee=over_limit_fee,
    )

    account.last_statement = stmt
    account.statements.append(stmt)

    account.add_log(day, "CYCLE_END",
                    cycle=cycle_num,
                    grace_eligible=account.grace_period_eligible,
                    interest=str(interest_result["total_interest"]),
                    purchase_interest=str(interest_result["purchase_interest"]),
                    cash_advance_interest=str(interest_result["cash_advance_interest"]),
                    new_balance=str(new_balance),
                    min_payment=str(min_payment),
                    due_day=due_day,
                    late_fee=str(late_fee),
                    over_limit_fee=str(over_limit_fee))

    # ---------------------------------------------------------------
    # 7. Reset for next cycle
    # ---------------------------------------------------------------
    for bucket in account.all_buckets():
        bucket.reset_cycle()
    account.payments_this_cycle = ZERO
    account.payment_returned_this_cycle = False
    account.cycle_start_day = day + 1

    # Check dispute deadlines
    _check_dispute_deadlines(account, day)


# ===================================================================
# Default handling
# ===================================================================

def _trigger_default(account: Account, day: int, code: DefaultCode, reason: str) -> None:
    if code not in account.default_triggers:
        account.default_triggers.append(code)
    if account.status == AccountStatus.ACTIVE:
        account.status = AccountStatus.DEFAULT
        account.default_day = day
    account.add_log(day, "DEFAULT_TRIGGERED", code=code.name, reason=reason)


# ===================================================================
# Dispute handling
# ===================================================================

def _handle_billing_error(account: Account, event: BillingErrorClaimed, day: int) -> None:
    if event.method != "written":
        account.add_log(day, "DISPUTE_REJECTED", reason="oral_only")
        dispute = Dispute(
            dispute_id=account.next_dispute_id,
            filed_day=day,
            amount=event.amount,
            error_on_statement_day=event.error_on_statement_day,
            method=event.method,
            status=DisputeStatus.REJECTED_ORAL_ONLY,
        )
        account.disputes.append(dispute)
        account.next_dispute_id += 1
        return

    # Check 60-day window
    days_since_statement = day - event.error_on_statement_day
    if days_since_statement > 60:
        account.add_log(day, "DISPUTE_REJECTED", reason="outside_60_day_window")
        return

    dispute = Dispute(
        dispute_id=account.next_dispute_id,
        filed_day=day,
        amount=event.amount,
        error_on_statement_day=event.error_on_statement_day,
        method=event.method,
        status=DisputeStatus.UNDER_INVESTIGATION,
        ack_deadline=day + 30,
        resolution_deadline=day + 90,
    )
    account.disputes.append(dispute)
    account.next_dispute_id += 1

    account.add_log(day, "DISPUTE_FILED",
                    dispute_id=dispute.dispute_id,
                    amount=str(event.amount),
                    ack_deadline=dispute.ack_deadline,
                    resolution_deadline=dispute.resolution_deadline)


def _handle_dispute_ack(account: Account, event: DisputeAcknowledged, day: int) -> None:
    for d in account.disputes:
        if d.dispute_id == event.dispute_id:
            d.ack_day = day
            on_time = day <= d.ack_deadline
            if not on_time:
                d.cu_failed = True
                d.cu_failure_type = "late_ack"
                d.status = DisputeStatus.CU_FAILED_PROCEDURE
            account.add_log(day, "DISPUTE_ACKNOWLEDGED",
                            dispute_id=event.dispute_id, on_time=on_time)
            break


def _handle_dispute_resolved_favor(account: Account, event: DisputeResolvedInFavor, day: int) -> None:
    for d in account.disputes:
        if d.dispute_id == event.dispute_id:
            d.status = DisputeStatus.RESOLVED_IN_FAVOR
            d.resolution_day = day
            # Reverse the disputed amount
            account.purchases.apply_payment(d.amount)
            account.add_log(day, "DISPUTE_RESOLVED_IN_FAVOR",
                            dispute_id=event.dispute_id,
                            amount_reversed=str(d.amount))
            break


def _handle_dispute_resolved_against(account: Account, event: DisputeResolvedAgainst, day: int) -> None:
    for d in account.disputes:
        if d.dispute_id == event.dispute_id:
            d.status = DisputeStatus.RESOLVED_AGAINST
            d.resolution_day = day
            account.add_log(day, "DISPUTE_RESOLVED_AGAINST",
                            dispute_id=event.dispute_id,
                            amount_owed=str(event.amount_owed))
            break


def _handle_cardholder_rejects(account: Account, event: CardholderRejectsResolution, day: int) -> None:
    for d in account.disputes:
        if d.dispute_id == event.dispute_id:
            d.status = DisputeStatus.CARDHOLDER_REJECTED_RESOLUTION
            account.add_log(day, "CARDHOLDER_REJECTS_RESOLUTION",
                            dispute_id=event.dispute_id)
            break


def _handle_purchase_dispute(account: Account, event: PurchaseDisputeFiled, day: int) -> None:
    # Validate all conditions per contract
    geo_ok = event.merchant_in_home_state or event.distance_from_home_miles <= 100
    amount_ok = event.purchase_amount > Decimal("50")
    geo_exception = event.via_cu_advertisement or event.cu_owns_merchant

    valid = (
        (geo_ok and amount_ok or geo_exception)
        and event.used_card_directly
        and not event.paid_in_full
        and event.good_faith_attempt
    )

    account.add_log(day, "PURCHASE_DISPUTE",
                    valid=valid,
                    amount=str(event.amount))


def _check_dispute_deadlines(account: Account, day: int) -> None:
    """Check if CU has missed any dispute deadlines."""
    for d in account.disputes:
        if d.status != DisputeStatus.UNDER_INVESTIGATION:
            continue
        # Check ack deadline
        if d.ack_day is None and day > d.ack_deadline:
            d.cu_failed = True
            d.cu_failure_type = "late_ack"
            account.add_log(day, "CU_MISSED_ACK_DEADLINE",
                            dispute_id=d.dispute_id)
        # Check resolution deadline
        if d.resolution_day is None and day > d.resolution_deadline:
            d.cu_failed = True
            d.cu_failure_type = "late_resolution"
            account.add_log(day, "CU_MISSED_RESOLUTION_DEADLINE",
                            dispute_id=d.dispute_id)


# ===================================================================
# Unauthorized Use
# ===================================================================

def _handle_unauthorized_reported(account: Account, event: UnauthorizedUseReported, day: int) -> None:
    total_liability = ZERO
    for rec in account.unauthorized_uses:
        if not rec.reported:
            rec.reported = True
            rec.report_day = day
            # Assess liability
            if rec.tx_type == "atm_cash":
                # Zero-liability exception for ATM
                rec.liability_assessed = min(rec.amount, Decimal("50.00"))
            elif rec.gross_negligence:
                rec.liability_assessed = min(rec.amount, Decimal("50.00"))
            else:
                # VISA zero-liability
                rec.liability_assessed = ZERO
            total_liability = to_cents(total_liability + rec.liability_assessed)

    account.add_log(day, "UNAUTHORIZED_USE_REPORTED",
                    method=event.method,
                    total_liability=str(total_liability))
