"""Parse statement history HTML files into structured cycle data.

Extracts account parameters and per-cycle transactions/payments/fees
from the test statement HTML format.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from html.parser import HTMLParser

ZERO = Decimal("0.00")


@dataclass
class Transaction:
    post_date: date
    description: str
    category: str  # "Purchase", "Cash Advance", "Payment", "Fee"
    amount: Decimal
    clause_ref: str = ""  # for fees: "Agreement Clause 7 - Late Payment Fee"


@dataclass
class CycleData:
    """One billing cycle extracted from the statement HTML."""
    cycle_number: int
    cycle_start: date
    cycle_end: date
    days_in_cycle: int
    previous_balance: Decimal = ZERO
    new_balance: Decimal = ZERO
    minimum_payment: Decimal = ZERO
    payment_due_date: Optional[date] = None
    transactions: list[Transaction] = field(default_factory=list)
    interest_charged: Decimal = ZERO
    total_fees: Decimal = ZERO
    total_purchases: Decimal = ZERO
    total_cash_advances: Decimal = ZERO
    total_payments: Decimal = ZERO


@dataclass
class AccountParams:
    """Account-level parameters extracted from the HTML comment block."""
    cardholder_name: str = ""
    account_number: str = ""
    credit_limit: Decimal = ZERO
    purchase_apr: Decimal = ZERO
    purchase_daily_rate: Decimal = ZERO
    cash_advance_apr: Decimal = ZERO
    cash_advance_daily_rate: Decimal = ZERO
    minimum_payment_pct: Decimal = ZERO
    minimum_payment_floor: Decimal = ZERO
    grace_period_days: int = 25
    late_fee: Decimal = ZERO
    late_fee_subsequent: Optional[Decimal] = None
    returned_payment_fee: Decimal = ZERO
    over_credit_limit_fee: Decimal = ZERO
    foreign_transaction_pct: Decimal = ZERO
    cash_advance_fee_pct: Decimal = ZERO
    cash_advance_fee_min: Decimal = ZERO
    interest_method: str = "average_daily_balance_including_current_transactions"
    # Whether purchases and cash advances share one ADB or have separate buckets
    single_rate: bool = True
    # Whether grace requires previous cycle to also have had grace (trailing interest)
    # WesTex: True (paying statement balance doesn't restore grace same cycle)
    # USFederalCU: False (paying statement balance in full restores grace)
    trailing_interest_grace: bool = True


@dataclass
class StatementHistory:
    """Complete parsed statement history."""
    params: AccountParams
    cycles: list[CycleData]


def parse_statement_html(html_path: str) -> StatementHistory:
    """Parse a statement HTML file into structured data."""
    with open(html_path, "r") as f:
        html = f.read()

    params = _parse_params(html)
    cycles = _parse_cycles(html, params)
    return StatementHistory(params=params, cycles=cycles)


def _parse_params(html: str) -> AccountParams:
    """Extract account parameters from the HTML comment block."""
    params = AccountParams()

    # Extract the comment block
    comment_match = re.search(r'<!--\s*={3,}(.*?)={3,}\s*-->', html, re.DOTALL)
    if not comment_match:
        return params

    block = comment_match.group(1)

    # Cardholder name
    m = re.search(r'Cardholder:\s*(.+)', block)
    if m:
        params.cardholder_name = m.group(1).strip()

    # Account number
    m = re.search(r'Account:\s*(.+)', block)
    if m:
        params.account_number = m.group(1).strip()

    # Credit limit
    m = re.search(r'Credit Limit:\s*\$?([\d,]+\.?\d*)', block)
    if m:
        params.credit_limit = Decimal(m.group(1).replace(",", ""))

    # APR - might be single or dual
    m = re.search(r'APR:\s*([\d.]+)%', block)
    if m:
        params.purchase_apr = Decimal(m.group(1))
        params.cash_advance_apr = Decimal(m.group(1))
        params.single_rate = True

    # Purchase APR (dual rate)
    m = re.search(r'purchase_apr:\s*([\d.]+)', block)
    if m:
        params.purchase_apr = Decimal(m.group(1))
        params.single_rate = False

    # Cash advance APR (dual rate)
    m = re.search(r'cash_advance_apr:\s*([\d.]+)', block)
    if m:
        params.cash_advance_apr = Decimal(m.group(1))
        if params.cash_advance_apr != params.purchase_apr:
            params.single_rate = False

    # Daily rates
    m = re.search(r'daily_periodic_rate:\s*([\d.]+)', block)
    if m:
        params.purchase_daily_rate = Decimal(m.group(1))
        params.cash_advance_daily_rate = Decimal(m.group(1))

    m = re.search(r'purchase_daily_rate:\s*([\d.]+)', block)
    if m:
        params.purchase_daily_rate = Decimal(m.group(1))

    m = re.search(r'cash_advance_daily_rate:\s*([\d.]+)', block)
    if m:
        params.cash_advance_daily_rate = Decimal(m.group(1))

    # Minimum payment
    m = re.search(r'minimum_payment_pct:\s*([\d.]+)', block)
    if m:
        params.minimum_payment_pct = Decimal(m.group(1))

    m = re.search(r'minimum_payment_floor:\s*([\d.]+)', block)
    if m:
        params.minimum_payment_floor = Decimal(m.group(1))

    # Grace period
    m = re.search(r'grace_period_days:\s*(\d+)', block)
    if m:
        params.grace_period_days = int(m.group(1))

    # Fees
    m = re.search(r'late_fee:\s*([\d.]+)', block)
    if m:
        params.late_fee = Decimal(m.group(1))

    m = re.search(r'late_fee_first:\s*([\d.]+)', block)
    if m:
        params.late_fee = Decimal(m.group(1))

    m = re.search(r'late_fee_subsequent:\s*([\d.]+)', block)
    if m:
        params.late_fee_subsequent = Decimal(m.group(1))

    m = re.search(r'returned_payment_fee:\s*([\d.]+)', block)
    if m:
        params.returned_payment_fee = Decimal(m.group(1))

    m = re.search(r'over_credit_limit_fee:\s*([\d.]+)', block)
    if m:
        params.over_credit_limit_fee = Decimal(m.group(1))

    m = re.search(r'foreign_transaction_pct:\s*([\d.]+)', block)
    if m:
        params.foreign_transaction_pct = Decimal(m.group(1))

    # Cash advance fee
    m = re.search(r'cash_advance_fee:\s*max\((\d+)%,\s*\$(\d+)\)', block)
    if m:
        params.cash_advance_fee_pct = Decimal(m.group(1)) / Decimal("100")
        params.cash_advance_fee_min = Decimal(m.group(2))

    # Trailing interest: if single-rate agreement, use trailing interest rule
    # (WesTex style). Dual-rate agreements (USFederalCU) use standard rule.
    params.trailing_interest_grace = params.single_rate

    return params


def _parse_cycles(html: str, params: AccountParams) -> list[CycleData]:
    """Extract per-cycle data from the statement HTML."""
    cycles = []

    # Split by statement divs
    stmt_blocks = re.split(r'<div class="statement"[^>]*>', html)

    for i, block in enumerate(stmt_blocks[1:], 1):  # skip before first statement
        cycle = CycleData(cycle_number=i, cycle_start=date(2026, 1, 1), cycle_end=date(2026, 1, 31), days_in_cycle=31)

        # Billing cycle dates from meta line
        m = re.search(r'Billing Cycle:\s*(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})\s*\|\s*(\d+)\s*days', block)
        if m:
            cycle.cycle_start = datetime.strptime(m.group(1), "%m/%d/%Y").date()
            cycle.cycle_end = datetime.strptime(m.group(2), "%m/%d/%Y").date()
            cycle.days_in_cycle = int(m.group(3))

        # Summary box values
        _extract_summary(block, cycle)

        # Transactions
        _extract_transactions(block, cycle)

        # Payment due date
        m = re.search(r'Payment Due Date.*?<strong>(\d{2}/\d{2}/\d{4})</strong>', block, re.DOTALL)
        if m:
            cycle.payment_due_date = datetime.strptime(m.group(1), "%m/%d/%Y").date()

        cycles.append(cycle)

    return cycles


def _extract_summary(block: str, cycle: CycleData) -> None:
    """Extract summary box values."""
    def _find_box(label: str) -> Decimal:
        pattern = rf'{re.escape(label)}.*?class="value[^"]*">\s*-?\$?([\d,]+\.?\d*)'
        m = re.search(pattern, block, re.DOTALL)
        if m:
            return Decimal(m.group(1).replace(",", ""))
        return ZERO

    cycle.previous_balance = _find_box("Previous Balance")
    cycle.new_balance = _find_box("New Balance")
    cycle.total_purchases = _find_box("Purchases")
    cycle.total_cash_advances = _find_box("Cash Advances")
    cycle.total_fees = _find_box("Fees")
    cycle.interest_charged = _find_box("Interest Charged")

    # Payments
    m = re.search(r'Payments.*?class="value[^"]*">\s*-?\$?([\d,]+\.?\d*)', block, re.DOTALL)
    if m:
        cycle.total_payments = Decimal(m.group(1).replace(",", ""))

    # Minimum payment
    m = re.search(r'Minimum Payment Due.*?<strong>\$?([\d,]+\.?\d*)</strong>', block, re.DOTALL)
    if m:
        cycle.minimum_payment = Decimal(m.group(1).replace(",", ""))


def _extract_transactions(block: str, cycle: CycleData) -> None:
    """Extract individual transactions from the table rows."""
    year = cycle.cycle_start.year

    # Find all transaction rows: <tr><td>MM/DD</td><td>MM/DD</td><td>DESC</td><td>CAT</td><td class="amt">$AMT</td></tr>
    rows = re.findall(
        r'<tr[^>]*>\s*<td>(\d{2}/\d{2})</td>\s*<td>(\d{2}/\d{2})</td>\s*<td>([^<]+)</td>\s*<td>([^<]+)</td>\s*<td class="amt">-?\$?([\d,]+\.?\d*)</td>',
        block
    )

    for trans_date, post_date, desc, category, amount in rows:
        category = category.strip()
        desc = desc.strip()
        amt = Decimal(amount.replace(",", ""))
        pd = datetime.strptime(f"{post_date}/{year}", "%m/%d/%Y").date()

        cycle.transactions.append(Transaction(
            post_date=pd,
            description=desc,
            category=category,
            amount=amt,
        ))

    # Also extract fee rows: <tr class="fee-row"><td>MM/DD</td><td>DESC</td><td>CLAUSE</td><td class="amt">$AMT</td></tr>
    fee_rows = re.findall(
        r'<tr class="fee-row">\s*<td>(\d{2}/\d{2})</td>\s*<td>([^<]+)</td>\s*<td>([^<]+)</td>\s*<td class="amt">\$?([\d,]+\.?\d*)</td>',
        block
    )
    for fee_date, desc, clause, amount in fee_rows:
        pd = datetime.strptime(f"{fee_date}/{year}", "%m/%d/%Y").date()
        cycle.transactions.append(Transaction(
            post_date=pd,
            description=desc.strip(),
            category="Fee",
            amount=Decimal(amount.replace(",", "")),
            clause_ref=clause.strip(),
        ))
