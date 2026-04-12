"""Test scenarios with hand-calculated expected outcomes.

Each test feeds injected events into the simulator and checks the
exact dollar amounts, states, and flags produced.
"""

import pytest
from decimal import Decimal

from engine.events import (
    AccountOpened, Purchase, CashAdvanceATM, CashAdvanceOther,
    BalanceTransfer, PaymentReceived, PaymentReturned, CycleEnd,
    BillingErrorClaimed, DisputeAcknowledged, DisputeResolvedInFavor,
    DisputeResolvedAgainst, CardholderRejectsResolution,
    UnauthorizedUse, UnauthorizedUseReported, GrossNegligenceFlagged,
    AuthorizedUserAdded, AuthorizedUserRevoked, JointApplicantWithdrawal,
    CardIssued, AccountStatus, DisputeStatus, DefaultCode,
)
from engine.simulator import simulate
from engine.payments import compute_minimum_payment

D = Decimal


def _open(day=1, limit="5000", apr_p="10.9", apr_ca="12.9", **kw):
    """Helper to create a standard AccountOpened event."""
    return AccountOpened(
        day=day,
        cardholder_name=kw.get("name", "Jane Doe"),
        credit_limit=D(limit),
        apr_purchase=D(apr_p),
        apr_cash_advance=D(apr_ca),
        card_product=kw.get("product", "platinum"),
        is_joint=kw.get("is_joint", False),
        joint_applicant_name=kw.get("joint_name", ""),
        home_state=kw.get("home_state", "TX"),
    )


# ===================================================================
# T01: Grace Period Active — Pay in Full, Zero Interest
# ===================================================================

class TestT01GraceActive:

    def test_cycle1_interest_zero(self):
        events = [
            _open(),
            Purchase(day=5, amount=D("1000")),
            CycleEnd(day=30),
        ]
        acct = simulate(events)
        stmt = acct.statements[0]
        assert stmt.total_interest == D("0.00")  # T01-A1

    def test_cycle1_new_balance(self):
        events = [
            _open(),
            Purchase(day=5, amount=D("1000")),
            CycleEnd(day=30),
        ]
        acct = simulate(events)
        stmt = acct.statements[0]
        assert stmt.new_balance == D("1000.00")  # T01-A2

    def test_cycle1_minimum_payment(self):
        events = [
            _open(),
            Purchase(day=5, amount=D("1000")),
            CycleEnd(day=30),
        ]
        acct = simulate(events)
        stmt = acct.statements[0]
        assert stmt.minimum_payment == D("30.00")  # T01-A3

    def test_cycle1_grace_eligible(self):
        events = [
            _open(),
            Purchase(day=5, amount=D("1000")),
            CycleEnd(day=30),
        ]
        acct = simulate(events)
        stmt = acct.statements[0]
        assert stmt.grace_period_eligible is True  # T01-A4

    def test_full_payment_cycle2_zero_interest(self):
        events = [
            _open(),
            Purchase(day=5, amount=D("1000")),
            CycleEnd(day=30),
            PaymentReceived(day=40, amount=D("1000")),
            CycleEnd(day=60),
        ]
        acct = simulate(events)
        stmt2 = acct.statements[1]
        assert stmt2.total_interest == D("0.00")  # T01-A5

    def test_full_payment_cycle2_zero_balance(self):
        events = [
            _open(),
            Purchase(day=5, amount=D("1000")),
            CycleEnd(day=30),
            PaymentReceived(day=40, amount=D("1000")),
            CycleEnd(day=60),
        ]
        acct = simulate(events)
        stmt2 = acct.statements[1]
        assert stmt2.new_balance == D("0.00")  # T01-A6

    def test_full_payment_cycle2_grace_remains(self):
        events = [
            _open(),
            Purchase(day=5, amount=D("1000")),
            CycleEnd(day=30),
            PaymentReceived(day=40, amount=D("1000")),
            CycleEnd(day=60),
        ]
        acct = simulate(events)
        stmt2 = acct.statements[1]
        assert stmt2.grace_period_eligible is True  # T01-A7

    def test_account_status_active(self):
        events = [
            _open(),
            Purchase(day=5, amount=D("1000")),
            CycleEnd(day=30),
            PaymentReceived(day=40, amount=D("1000")),
            CycleEnd(day=60),
        ]
        acct = simulate(events)
        assert acct.status == AccountStatus.ACTIVE  # T01-A8

    def test_no_fees(self):
        events = [
            _open(),
            Purchase(day=5, amount=D("1000")),
            CycleEnd(day=30),
            PaymentReceived(day=40, amount=D("1000")),
            CycleEnd(day=60),
        ]
        acct = simulate(events)
        assert acct.fees_balance == D("0.00")  # T01-A9


# ===================================================================
# T02: Cash Advance — Interest from Post Date, No Grace
# ===================================================================

class TestT02CashAdvance:

    def test_cycle1_interest(self):
        events = [
            _open(),
            CashAdvanceATM(day=10, amount=D("500"), atm_operator_fee=D("3")),
            CycleEnd(day=30),
        ]
        acct = simulate(events)
        stmt = acct.statements[0]
        assert stmt.cash_advance_interest == D("3.71")  # T02-A1

    def test_cycle1_new_balance(self):
        events = [
            _open(),
            CashAdvanceATM(day=10, amount=D("500"), atm_operator_fee=D("3")),
            CycleEnd(day=30),
        ]
        acct = simulate(events)
        stmt = acct.statements[0]
        assert stmt.new_balance == D("506.71")  # T02-A2

    def test_cycle1_minimum_payment(self):
        events = [
            _open(),
            CashAdvanceATM(day=10, amount=D("500"), atm_operator_fee=D("3")),
            CycleEnd(day=30),
        ]
        acct = simulate(events)
        stmt = acct.statements[0]
        assert stmt.minimum_payment == D("15.20")  # T02-A3

    def test_atm_fee_assessed(self):
        events = [
            _open(),
            CashAdvanceATM(day=10, amount=D("500"), atm_operator_fee=D("3")),
            CycleEnd(day=30),
        ]
        acct = simulate(events)
        # ATM fee is treated as purchase
        assert acct.statements[0].new_balance == D("506.71")  # T02-A4 (covered by A2)

    def test_purchase_grace_still_eligible(self):
        events = [
            _open(),
            CashAdvanceATM(day=10, amount=D("500"), atm_operator_fee=D("3")),
            CycleEnd(day=30),
        ]
        acct = simulate(events)
        stmt = acct.statements[0]
        # Cash advance doesn't kill purchase grace
        assert stmt.grace_period_eligible is True  # T02-A5


# ===================================================================
# T03: Grace Period Lost — Min Payment Only, Interest Next Cycle
# ===================================================================

class TestT03GraceLost:

    def test_cycle1_no_interest(self):
        events = [
            _open(),
            Purchase(day=5, amount=D("1000")),
            CycleEnd(day=30),
            PaymentReceived(day=40, amount=D("30")),  # min only
            CycleEnd(day=60),
        ]
        acct = simulate(events)
        assert acct.statements[0].total_interest == D("0.00")  # T03-A1

    def test_cycle1_balance(self):
        events = [
            _open(),
            Purchase(day=5, amount=D("1000")),
            CycleEnd(day=30),
            PaymentReceived(day=40, amount=D("30")),
            CycleEnd(day=60),
        ]
        acct = simulate(events)
        assert acct.statements[0].new_balance == D("1000.00")  # T03-A2

    def test_cycle2_grace_lost(self):
        events = [
            _open(),
            Purchase(day=5, amount=D("1000")),
            CycleEnd(day=30),
            PaymentReceived(day=40, amount=D("30")),
            CycleEnd(day=60),
        ]
        acct = simulate(events)
        assert acct.statements[1].grace_period_eligible is False  # T03-A3

    def test_cycle2_interest(self):
        events = [
            _open(),
            Purchase(day=5, amount=D("1000")),
            CycleEnd(day=30),
            PaymentReceived(day=40, amount=D("30")),
            CycleEnd(day=60),
        ]
        acct = simulate(events)
        assert acct.statements[1].purchase_interest == D("8.77")  # T03-A4

    def test_cycle2_new_balance(self):
        events = [
            _open(),
            Purchase(day=5, amount=D("1000")),
            CycleEnd(day=30),
            PaymentReceived(day=40, amount=D("30")),
            CycleEnd(day=60),
        ]
        acct = simulate(events)
        assert acct.statements[1].new_balance == D("978.77")  # T03-A5

    def test_cycle2_minimum_payment(self):
        events = [
            _open(),
            Purchase(day=5, amount=D("1000")),
            CycleEnd(day=30),
            PaymentReceived(day=40, amount=D("30")),
            CycleEnd(day=60),
        ]
        acct = simulate(events)
        assert acct.statements[1].minimum_payment == D("29.36")  # T03-A6

    def test_account_still_active(self):
        events = [
            _open(),
            Purchase(day=5, amount=D("1000")),
            CycleEnd(day=30),
            PaymentReceived(day=40, amount=D("30")),
            CycleEnd(day=60),
        ]
        acct = simulate(events)
        assert acct.status == AccountStatus.ACTIVE  # T03-A7


# ===================================================================
# T04: Late Payment — Fee + Default
# ===================================================================

class TestT04LatePayment:

    def _run(self):
        events = [
            _open(),
            Purchase(day=5, amount=D("1000")),
            CycleEnd(day=30),
            # NO payment — due day 55 passes
            CycleEnd(day=60),
        ]
        return simulate(events)

    def test_cycle2_interest(self):
        acct = self._run()
        assert acct.statements[1].purchase_interest == D("8.96")  # T04-A1

    def test_cycle2_late_fee(self):
        acct = self._run()
        assert acct.statements[1].late_fee == D("25.00")  # T04-A2

    def test_cycle2_new_balance(self):
        acct = self._run()
        assert acct.statements[1].new_balance == D("1033.96")  # T04-A3

    def test_cycle2_minimum_payment(self):
        acct = self._run()
        assert acct.statements[1].minimum_payment == D("31.02")  # T04-A4

    def test_default_triggered(self):
        acct = self._run()
        assert DefaultCode.D1 in acct.default_triggers  # T04-A5, T04-A6

    def test_account_status_default(self):
        acct = self._run()
        assert acct.status == AccountStatus.DEFAULT  # T04-A7


# ===================================================================
# T08: Payment Waterfall — Two Rate Buckets
# ===================================================================

class TestT08Waterfall:

    def _run(self):
        events = [
            _open(),
            Purchase(day=5, amount=D("1000")),
            CashAdvanceATM(day=5, amount=D("500"), atm_operator_fee=D("0")),
            CycleEnd(day=30),
            PaymentReceived(day=40, amount=D("100")),
            CycleEnd(day=60),
        ]
        return simulate(events)

    def test_cycle1_cash_advance_interest(self):
        acct = self._run()
        assert acct.statements[0].cash_advance_interest == D("4.59")  # T08-A1

    def test_cycle1_purchase_interest(self):
        acct = self._run()
        assert acct.statements[0].purchase_interest == D("0.00")  # T08-A2

    def test_cycle1_new_balance(self):
        acct = self._run()
        assert acct.statements[0].new_balance == D("1504.59")  # T08-A3


# ===================================================================
# T09: Billing Dispute — Valid Written Within 60 Days
# ===================================================================

class TestT09DisputeValid:

    def _run(self):
        events = [
            _open(),
            Purchase(day=10, amount=D("800")),
            CycleEnd(day=30),
            BillingErrorClaimed(day=45, error_on_statement_day=30,
                                amount=D("800"), description="Unknown charge",
                                method="written"),
        ]
        return simulate(events)

    def test_dispute_accepted(self):
        acct = self._run()
        assert len(acct.disputes) == 1
        assert acct.disputes[0].status == DisputeStatus.UNDER_INVESTIGATION  # T09-A1, A2

    def test_ack_deadline(self):
        acct = self._run()
        assert acct.disputes[0].ack_deadline == 75  # T09-A3

    def test_resolution_deadline(self):
        acct = self._run()
        assert acct.disputes[0].resolution_deadline == 135  # T09-A5


# ===================================================================
# T10: Billing Dispute — Oral Only
# ===================================================================

class TestT10DisputeOral:

    def test_oral_rejected(self):
        events = [
            _open(),
            Purchase(day=10, amount=D("800")),
            CycleEnd(day=30),
            BillingErrorClaimed(day=45, error_on_statement_day=30,
                                amount=D("800"), description="Unknown",
                                method="oral"),
        ]
        acct = simulate(events)
        assert acct.disputes[0].status == DisputeStatus.REJECTED_ORAL_ONLY  # T10-A5


# ===================================================================
# T12: Unauthorized ATM — $50 Cap
# ===================================================================

class TestT12UnauthorizedATM:

    def test_atm_liability_capped(self):
        events = [
            _open(),
            UnauthorizedUse(day=10, amount=D("300"), tx_type="atm_cash"),
            UnauthorizedUseReported(day=12, method="oral"),
        ]
        acct = simulate(events)
        assert acct.unauthorized_uses[0].liability_assessed == D("50.00")  # T12-A2


# ===================================================================
# T13: Unauthorized Purchase — VISA Zero Liability
# ===================================================================

class TestT13UnauthorizedPurchase:

    def test_purchase_zero_liability(self):
        events = [
            _open(),
            UnauthorizedUse(day=10, amount=D("2000"), tx_type="purchase"),
            UnauthorizedUseReported(day=15, method="written"),
        ]
        acct = simulate(events)
        assert acct.unauthorized_uses[0].liability_assessed == D("0.00")  # T13-A2


# ===================================================================
# T15: Minimum Payment Edge Cases
# ===================================================================

class TestT15MinPayment:

    def test_zero_balance(self):
        assert compute_minimum_payment(D("0")) == D("0.00")

    def test_10_dollars(self):
        assert compute_minimum_payment(D("10.00")) == D("10.00")

    def test_15_dollars(self):
        assert compute_minimum_payment(D("15.00")) == D("15.00")

    def test_15_01(self):
        assert compute_minimum_payment(D("15.01")) == D("15.00")

    def test_500(self):
        assert compute_minimum_payment(D("500.00")) == D("15.00")

    def test_600(self):
        assert compute_minimum_payment(D("600.00")) == D("18.00")

    def test_1000(self):
        assert compute_minimum_payment(D("1000.00")) == D("30.00")

    def test_5000(self):
        assert compute_minimum_payment(D("5000.00")) == D("150.00")


# ===================================================================
# T16: Authorized User Revocation
# ===================================================================

class TestT16AuthUserRevoke:

    def test_both_conditions_effective(self):
        events = [
            _open(),
            AuthorizedUserAdded(day=1, user_name="Bob"),
            AuthorizedUserRevoked(day=15, user_name="Bob",
                                  written_notice=True, card_returned=True),
        ]
        acct = simulate(events)
        assert "Bob" not in acct.authorized_users  # T16-a

    def test_missing_card_not_effective(self):
        events = [
            _open(),
            AuthorizedUserAdded(day=1, user_name="Bob"),
            AuthorizedUserRevoked(day=15, user_name="Bob",
                                  written_notice=True, card_returned=False),
        ]
        acct = simulate(events)
        assert "Bob" in acct.authorized_users  # T16-b

    def test_missing_notice_not_effective(self):
        events = [
            _open(),
            AuthorizedUserAdded(day=1, user_name="Bob"),
            AuthorizedUserRevoked(day=15, user_name="Bob",
                                  written_notice=False, card_returned=True),
        ]
        acct = simulate(events)
        assert "Bob" in acct.authorized_users  # T16-c


# ===================================================================
# T17: Joint Account Withdrawal
# ===================================================================

class TestT17JointWithdrawal:

    def test_withdrawal_records(self):
        events = [
            _open(is_joint=True, joint_name="John", name="Jane"),
            Purchase(day=5, amount=D("500"), by_user="Jane"),
            JointApplicantWithdrawal(day=15, applicant_name="John",
                                     written_notice=True),
            Purchase(day=20, amount=D("300"), by_user="Jane"),
        ]
        acct = simulate(events)

        # John should have a liability record showing withdrawal on day 15
        john_records = [r for r in acct.liability_records if r.party == "John"]
        assert len(john_records) == 1
        assert john_records[0].withdrawn_day == 15  # T17-A5
        assert john_records[0].liable_for_charges_before == 15  # T17-A1, A2
