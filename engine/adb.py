"""Average Daily Balance tracker with full changelog for explainer output.

Tracks the running balance day-by-day, recording every change with
date ranges and activity descriptions. Produces the ADB Detail Table
that shows a judge exactly how interest was calculated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

ZERO = Decimal("0.00")
CENT = Decimal("0.01")


def _round(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class ADBEntry:
    """One row in the ADB Detail Table."""
    start_date: date
    end_date: date
    days: int
    daily_balance: Decimal
    subtotal: Decimal  # days * daily_balance
    activity: str  # e.g. "+Purchase $215.88" or "-Payment $15.00"


@dataclass
class ADBTracker:
    """Tracks daily balance changes through a billing cycle.

    Call `post()` for every balance-changing event in date order.
    At cycle end, call `finalize()` to get ADB, interest, and the detail table.
    """
    cycle_start: date
    cycle_end: date
    opening_balance: Decimal = ZERO

    _current_balance: Decimal = ZERO
    _current_start: Optional[date] = None
    _entries: list[ADBEntry] = field(default_factory=list)
    _pending_activity: str = ""
    _finalized: bool = False

    def __post_init__(self):
        self._current_balance = _round(self.opening_balance)
        self._current_start = self.cycle_start
        self._pending_activity = "Previous balance carried" if self.opening_balance > ZERO else "Opening balance"

    def post(self, event_date: date, amount: Decimal, activity: str) -> None:
        """Record a balance change (positive = charge, negative = payment/credit)."""
        # Close the previous date range
        if event_date > self._current_start:
            self._close_range(event_date - timedelta(days=1))

        # Apply the change
        self._current_balance = _round(self._current_balance + amount)
        self._current_start = event_date
        self._pending_activity = activity

    def finalize(self, rate: Decimal, days_in_cycle: int,
                 rate_type: str = "daily") -> dict:
        """Close the cycle and compute ADB + interest.

        Args:
            rate: The periodic rate (daily or monthly depending on rate_type).
            days_in_cycle: Number of days in the billing cycle.
            rate_type: "daily" → Interest = ADB × rate × days
                       "monthly" → Interest = ADB × rate

        Returns dict with entries, sum, adb, rate, interest.
        """
        if not self._finalized:
            self._close_range(self.cycle_end)
            self._finalized = True

        total = sum(e.subtotal for e in self._entries)
        adb = _round(total / Decimal(str(days_in_cycle))) if days_in_cycle > 0 else ZERO

        if rate_type == "monthly":
            interest = _round(adb * rate)
        else:
            interest = _round(adb * rate * Decimal(str(days_in_cycle)))

        return {
            "entries": list(self._entries),
            "sum_of_balances": _round(total),
            "days_in_cycle": days_in_cycle,
            "adb": adb,
            "rate": rate,
            "rate_type": rate_type,
            "interest": interest,
        }

    @property
    def current_balance(self) -> Decimal:
        return self._current_balance

    def _close_range(self, end_date: date) -> None:
        """Close a date range and add it to entries."""
        if self._current_start is None:
            return
        days = (end_date - self._current_start).days + 1
        if days <= 0:
            return
        subtotal = _round(self._current_balance * Decimal(str(days)))
        self._entries.append(ADBEntry(
            start_date=self._current_start,
            end_date=end_date,
            days=days,
            daily_balance=self._current_balance,
            subtotal=subtotal,
            activity=self._pending_activity,
        ))
        self._current_start = end_date + timedelta(days=1)
        self._pending_activity = ""


@dataclass
class DualADBTracker:
    """Tracks separate ADBs for purchases and cash advances (different APRs).

    Used when the agreement has different rates for purchases vs cash advances
    (e.g., USFederalCU: 17.99% purchases, 21.99% cash advances).
    """
    cycle_start: date
    cycle_end: date
    opening_purchase_balance: Decimal = ZERO
    opening_cash_advance_balance: Decimal = ZERO
    purchase_daily_rate: Decimal = ZERO
    cash_advance_daily_rate: Decimal = ZERO

    purchases: ADBTracker = field(init=False)
    cash_advances: ADBTracker = field(init=False)

    def __post_init__(self):
        self.purchases = ADBTracker(
            cycle_start=self.cycle_start,
            cycle_end=self.cycle_end,
            opening_balance=self.opening_purchase_balance,
        )
        self.cash_advances = ADBTracker(
            cycle_start=self.cycle_start,
            cycle_end=self.cycle_end,
            opening_balance=self.opening_cash_advance_balance,
        )

    def finalize(self, days_in_cycle: int) -> dict:
        purchase_result = self.purchases.finalize(self.purchase_daily_rate, days_in_cycle)
        ca_result = self.cash_advances.finalize(self.cash_advance_daily_rate, days_in_cycle)
        return {
            "purchases": purchase_result,
            "cash_advances": ca_result,
            "total_interest": _round(purchase_result["interest"] + ca_result["interest"]),
        }
