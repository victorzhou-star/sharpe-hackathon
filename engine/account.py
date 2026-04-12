"""Credit card account state model with balance buckets."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from engine.events import AccountStatus, DisputeStatus, DefaultCode

ZERO = Decimal("0.00")
CENT = Decimal("0.01")


def to_cents(value: Decimal) -> Decimal:
    """Round to nearest cent using half-up."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class BalanceBucket:
    """Tracks a balance at a specific APR — purchases, cash advances, or balance transfers."""
    name: str
    apr: Decimal
    daily_rate: Decimal
    balance: Decimal = ZERO
    daily_balances: list[Decimal] = field(default_factory=list)

    # Balance transfer intro tracking
    intro_rate: Optional[Decimal] = None
    intro_expires_day: Optional[int] = None

    def post_charge(self, amount: Decimal) -> None:
        self.balance = to_cents(self.balance + amount)

    def apply_payment(self, amount: Decimal) -> Decimal:
        """Apply payment to this bucket. Returns amount actually applied."""
        applied = min(amount, self.balance)
        self.balance = to_cents(self.balance - applied)
        return applied

    def snapshot_daily_balance(self) -> None:
        self.daily_balances.append(self.balance)

    def compute_interest(self, days_in_cycle: int, current_day: int) -> Decimal:
        """Compute interest charge for the cycle from daily_balances."""
        if not self.daily_balances:
            return ZERO
        effective_rate = self.effective_daily_rate(current_day)
        total = sum(self.daily_balances)
        interest = total * effective_rate
        return to_cents(interest)

    def effective_daily_rate(self, current_day: int) -> Decimal:
        """Return the daily rate, accounting for intro periods."""
        if (self.intro_rate is not None
                and self.intro_expires_day is not None
                and current_day <= self.intro_expires_day):
            return self.intro_rate
        return self.daily_rate

    def reset_cycle(self) -> None:
        self.daily_balances = []


@dataclass
class Dispute:
    dispute_id: int
    filed_day: int
    amount: Decimal
    error_on_statement_day: int
    method: str  # "written" or "oral"
    status: DisputeStatus = DisputeStatus.FILED
    ack_deadline: int = 0
    resolution_deadline: int = 0
    ack_day: Optional[int] = None
    resolution_day: Optional[int] = None
    cu_failed: bool = False
    cu_failure_type: Optional[str] = None


@dataclass
class UnauthorizedUseRecord:
    day: int
    amount: Decimal
    tx_type: str  # "purchase", "atm_cash", "other"
    reported: bool = False
    report_day: Optional[int] = None
    gross_negligence: bool = False
    liability_assessed: Optional[Decimal] = None


@dataclass
class LiabilityRecord:
    """Tracks who is liable for what."""
    party: str
    liable_for_charges_after: Optional[int] = None  # None = liable for all
    liable_for_charges_before: Optional[int] = None  # None = liable for all
    withdrawn_day: Optional[int] = None


@dataclass
class Statement:
    cycle_number: int
    cycle_start_day: int
    cycle_end_day: int
    previous_balance: Decimal = ZERO
    total_purchases: Decimal = ZERO
    total_cash_advances: Decimal = ZERO
    total_balance_transfers: Decimal = ZERO
    total_fees: Decimal = ZERO
    total_interest: Decimal = ZERO
    purchase_interest: Decimal = ZERO
    cash_advance_interest: Decimal = ZERO
    balance_transfer_interest: Decimal = ZERO
    total_payments: Decimal = ZERO
    total_credits: Decimal = ZERO
    new_balance: Decimal = ZERO
    minimum_payment: Decimal = ZERO
    payment_due_day: int = 0
    grace_period_eligible: bool = True
    late_fee: Decimal = ZERO
    over_limit_fee: Decimal = ZERO
    returned_payment_fee: Decimal = ZERO
    foreign_transaction_fees: Decimal = ZERO
    other_fees: Decimal = ZERO


@dataclass
class Account:
    """Full credit card account state."""

    # Identity
    cardholder_name: str = ""
    joint_applicant_name: str = ""
    is_joint: bool = False
    home_state: str = "TX"
    home_address: str = ""
    card_product: str = "platinum"

    # Limits
    credit_limit: Decimal = Decimal("5000")

    # Balance buckets
    purchases: BalanceBucket = field(default_factory=lambda: BalanceBucket(
        name="purchases", apr=Decimal("10.9"), daily_rate=Decimal("0.0002986")))
    cash_advances: BalanceBucket = field(default_factory=lambda: BalanceBucket(
        name="cash_advances", apr=Decimal("12.9"), daily_rate=Decimal("0.0003534")))
    balance_transfers: BalanceBucket = field(default_factory=lambda: BalanceBucket(
        name="balance_transfers", apr=Decimal("8.9"), daily_rate=Decimal("0.00024383")))

    # Fee balance (not in a rate bucket — tracked for waterfall)
    fees_balance: Decimal = ZERO
    interest_balance: Decimal = ZERO
    collection_costs: Decimal = ZERO

    # Grace period
    grace_period_eligible: bool = True

    # Account status
    status: AccountStatus = AccountStatus.ACTIVE
    default_triggers: list[DefaultCode] = field(default_factory=list)
    default_day: Optional[int] = None

    # Billing
    cycle_number: int = 0
    cycle_start_day: int = 1
    last_statement: Optional[Statement] = None
    statements: list[Statement] = field(default_factory=list)

    # Payment tracking for the current cycle
    payments_this_cycle: Decimal = ZERO
    payment_returned_this_cycle: bool = False
    skip_payment_cycle: Optional[int] = None

    # Users
    authorized_users: list[str] = field(default_factory=list)
    liability_records: list[LiabilityRecord] = field(default_factory=list)

    # Disputes
    disputes: list[Dispute] = field(default_factory=list)
    next_dispute_id: int = 1

    # Unauthorized use tracking
    unauthorized_uses: list[UnauthorizedUseRecord] = field(default_factory=list)

    # Terms change tracking
    terms_changed_day: Optional[int] = None
    used_card_after_terms_change: bool = False

    # Execution log
    log: list[dict] = field(default_factory=list)

    @property
    def total_balance(self) -> Decimal:
        return to_cents(
            self.purchases.balance
            + self.cash_advances.balance
            + self.balance_transfers.balance
            + self.fees_balance
            + self.interest_balance
            + self.collection_costs
        )

    @property
    def principal_balance(self) -> Decimal:
        return to_cents(
            self.purchases.balance
            + self.cash_advances.balance
            + self.balance_transfers.balance
        )

    def all_buckets(self) -> list[BalanceBucket]:
        return [self.purchases, self.cash_advances, self.balance_transfers]

    def buckets_by_rate_ascending(self) -> list[BalanceBucket]:
        return sorted(self.all_buckets(), key=lambda b: b.effective_daily_rate(0))

    def buckets_by_rate_descending(self) -> list[BalanceBucket]:
        return sorted(self.all_buckets(), key=lambda b: b.effective_daily_rate(0), reverse=True)

    def snapshot_daily_balances(self) -> None:
        """Record daily balance for each bucket.

        Always record actual balances. Grace period filtering
        is handled at interest calculation time, not snapshot time.
        """
        self.purchases.snapshot_daily_balance()
        self.cash_advances.snapshot_daily_balance()
        self.balance_transfers.snapshot_daily_balance()

    def add_log(self, day: int, event_type: str, **kwargs) -> None:
        entry = {"day": day, "event": event_type, **kwargs}
        self.log.append(entry)
