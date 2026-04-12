"""Terminal output for cycle-by-cycle credit card analysis.

Produces clear, monospace-friendly output that walks a judge through
each billing cycle with full explanations for:
  2B: Interest calculation
  2C: Grace period
  2D: Fee justification
  2E: Payment waterfall
"""

from __future__ import annotations

from decimal import Decimal
from engine.cycle_engine import CycleResult, InterestExplanation
from engine.statement_input import AccountParams, CycleData, StatementHistory
from engine.adb import ZERO


def print_full_report(history: StatementHistory, results: list[CycleResult]) -> None:
    """Print the complete analysis to stdout."""
    params = history.params

    _print_header(params)

    for i, result in enumerate(results):
        cycle_data = history.cycles[i]
        _print_cycle(result, cycle_data, params, i + 1, len(results))

    _print_footer(results, params)


def _print_header(params: AccountParams) -> None:
    w = 72
    print()
    print("=" * w)
    print("  CREDIT CARD AGREEMENT ANALYSIS")
    print("=" * w)
    print(f"  Cardholder:       {params.cardholder_name}")
    print(f"  Account:          {params.account_number}")
    print(f"  Credit Limit:     ${params.credit_limit}")
    print(f"  Purchase APR:     {params.purchase_apr}%  (daily: {_pct(params.purchase_daily_rate)})")
    if not params.single_rate:
        print(f"  Cash Advance APR: {params.cash_advance_apr}%  (daily: {_pct(params.cash_advance_daily_rate)})")
    print(f"  Grace Period:     {params.grace_period_days} days")
    print(f"  Min Payment:      {params.minimum_payment_pct * 100}% or ${params.minimum_payment_floor}")
    print(f"  Late Fee:         ${params.late_fee}")
    print("=" * w)
    print()


def _print_cycle(r: CycleResult, cd: CycleData, params: AccountParams,
                 cycle_num: int, total_cycles: int) -> None:
    w = 72
    month = r.cycle_start.strftime("%B %Y")
    start = r.cycle_start.strftime("%m/%d/%Y")
    end = r.cycle_end.strftime("%m/%d/%Y")

    print()
    print("+" + "-" * (w - 2) + "+")
    print(f"|  CYCLE {cycle_num}: {month}".ljust(w - 1) + "|")
    print(f"|  Billing Period: {start} - {end} ({r.days_in_cycle} days)".ljust(w - 1) + "|")
    print("+" + "-" * (w - 2) + "+")
    print()

    # --- Summary ---
    print("  ACCOUNT SUMMARY")
    print("  " + "-" * 50)
    _row("Previous Balance", r.previous_balance)
    _row("+ Purchases", r.total_purchases)
    _row("+ Cash Advances", r.total_cash_advances)
    _row("+ Fees", r.total_fees)
    _row("+ Interest Charged", r.total_interest)
    _row("- Payments & Credits", r.total_payments)
    print("  " + "-" * 50)
    _row("= NEW BALANCE", r.new_balance, bold=True)
    print()
    due_str = r.payment_due_date.strftime("%m/%d/%Y") if r.payment_due_date else "N/A"
    _row("Minimum Payment Due", r.minimum_payment)
    _row("Payment Due Date", due_str)
    print()

    # --- Transactions ---
    if cd.transactions:
        print("  TRANSACTIONS")
        print("  " + "-" * 50)
        for tx in sorted(cd.transactions, key=lambda t: t.post_date):
            d = tx.post_date.strftime("%m/%d")
            sign = "-" if tx.category == "Payment" else "+"
            cat = tx.category.ljust(12)
            desc = tx.description[:30].ljust(30)
            amt = f"{sign}${tx.amount}"
            print(f"  {d}  {cat} {desc} {amt:>10}")
        print()

    # --- 2B: Interest Calculation ---
    _print_interest(r, params)

    # --- 2C: Grace Period ---
    _print_grace(r, params)

    # --- 2D: Fee Justification ---
    _print_fees(r)

    # --- 2E: Payment Waterfall ---
    _print_payments(r, params)

    print(f"  [{cycle_num}/{total_cycles}]")


def _print_interest(r: CycleResult, params: AccountParams) -> None:
    ie = r.interest_explanation
    if not ie:
        return

    print("  2B. HOW WAS INTEREST CALCULATED?")
    print("  " + "=" * 50)
    print()

    # Interest charge table
    print("  Rate Table:")
    print(f"  {'Balance Type':<20} {'Daily Rate':>12} {'APR':>8} {'ADB':>12} {'Days':>6} {'Interest':>10}")
    print("  " + "-" * 68)
    print(f"  {'Purchases':<20} {_pct(ie.purchase_rate):>12} {ie.purchase_apr:>7}% ${ie.purchase_adb:>10} {ie.days_in_cycle:>6} ${ie.purchase_interest:>9}")
    if params.cash_advance_apr != params.purchase_apr or ie.cash_advance_interest > ZERO:
        print(f"  {'Cash Advances':<20} {_pct(ie.cash_advance_rate):>12} {ie.cash_advance_apr:>7}% ${ie.cash_advance_adb:>10} {ie.days_in_cycle:>6} ${ie.cash_advance_interest:>9}")
    print("  " + "-" * 68)
    print(f"  {'TOTAL INTEREST':<20} {'':>12} {'':>8} {'':>12} {'':>6} ${ie.total_interest:>9}")
    print()

    # ADB detail table
    if ie.adb_entries:
        print("  Average Daily Balance Breakdown:")
        print(f"  {'Date Range':<16} {'Days':>5} {'Daily Balance':>14} {'Subtotal':>12}  {'Activity'}")
        print("  " + "-" * 68)
        total_days = 0
        total_sub = ZERO
        for entry in ie.adb_entries:
            s = entry.start_date.strftime("%m/%d")
            e = entry.end_date.strftime("%m/%d")
            print(f"  {s} - {e:<10} {entry.days:>5} ${entry.daily_balance:>13} ${entry.subtotal:>11}  {entry.activity}")
            total_days += entry.days
            total_sub += entry.subtotal
        print("  " + "-" * 68)
        print(f"  {'TOTAL':<16} {total_days:>5} {'':>14} ${total_sub:>11}")

        adb = ie.purchase_adb if ie.purchase_adb > ZERO else ie.cash_advance_adb
        print(f"  ADB = ${total_sub} / {total_days} days = ${adb}")

        if ie.total_interest > ZERO:
            rate = ie.purchase_rate if ie.purchase_interest > ZERO else ie.cash_advance_rate
            print(f"  Interest = ${adb} x {_pct(rate)} x {ie.days_in_cycle} = ${ie.total_interest}")
        elif ie.grace_note:
            print(f"  {ie.grace_note}")
        print()


def _print_grace(r: CycleResult, params: AccountParams) -> None:
    if not r.grace_explanation:
        return

    ge = r.grace_explanation
    status = "YES" if ge.eligible else "NO"

    print("  2C. WAS THE GRACE PERIOD HANDLED CORRECTLY?")
    print("  " + "=" * 50)
    print()
    print(f"  Grace Period: {status}")
    print()
    # Wrap the reason text
    for line in _wrap(ge.reason, 66):
        print(f"  {line}")
    print()
    print(f"  [Contract Ref: Section 6 — {params.grace_period_days}-day grace period")
    print(f"   on purchases if previous balance paid in full by due date.]")
    print()


def _print_fees(r: CycleResult) -> None:
    print("  2D. JUSTIFY EVERY FEE")
    print("  " + "=" * 50)
    print()

    if not r.fee_explanations:
        print("  No fees assessed this cycle.")
        print()
        return

    for fe in r.fee_explanations:
        d = fe.fee_date.strftime("%m/%d/%Y")
        print(f"  {d}  {fe.description:<30} ${fe.amount:>8}")
        print(f"          Clause: {fe.clause_ref}")
        for line in _wrap(fe.justification, 60):
            print(f"          {line}")
        print()


def _print_payments(r: CycleResult, params: AccountParams) -> None:
    print("  2E. HOW WERE PAYMENTS APPLIED?")
    print("  " + "=" * 50)
    print()

    if not r.payment_explanations:
        print("  No payments received this cycle.")
        print()
        return

    for pe in r.payment_explanations:
        d = pe.payment_date.strftime("%m/%d/%Y")
        print(f"  Payment of ${pe.total_amount} received {d}")
        print()
        print(f"  {'Step':<35} {'Amount':>10}  {'Applied To'}")
        print("  " + "-" * 66)
        for step in pe.steps:
            print(f"  {step.component:<35} ${step.amount:>9}  {step.applied_to}")
        if pe.excess_amount > ZERO:
            print(f"  {'Excess Above Minimum':<35} ${pe.excess_amount:>9}  {pe.excess_applied_to}")
        print("  " + "-" * 66)
        print(f"  {'TOTAL APPLIED':<35} ${pe.total_amount:>9}")
        print()
        print("  [Contract Ref: Section 10 — Minimum payment applied first to")
        print("   collection costs, then interest/fees, then principal.")
        print("   Excess applied to highest-rate balance first.]")
        print()


def _print_footer(results: list[CycleResult], params: AccountParams) -> None:
    w = 72
    print()
    print("=" * w)
    print("  ANALYSIS SUMMARY")
    print("=" * w)
    print()
    print(f"  {'Cycle':<8} {'Balance':>10} {'Interest':>10} {'Fees':>8} {'Grace':>7}")
    print("  " + "-" * 50)
    total_interest = ZERO
    total_fees = ZERO
    for r in results:
        grace = "YES" if r.grace_explanation and r.grace_explanation.eligible else "NO"
        print(f"  {r.cycle_number:<8} ${r.new_balance:>9} ${r.total_interest:>9} ${r.total_fees:>7} {grace:>7}")
        total_interest += r.total_interest
        total_fees += r.total_fees
    print("  " + "-" * 50)
    print(f"  {'TOTAL':<8} {'':>10} ${total_interest:>9} ${total_fees:>7}")
    print()
    final = results[-1].new_balance if results else ZERO
    print(f"  Final Balance: ${final}")
    print(f"  Total Interest Paid: ${total_interest}")
    print(f"  Total Fees Paid: ${total_fees}")
    print()
    print("=" * w)


# ===================================================================
# Helpers
# ===================================================================

def _row(label: str, value, bold: bool = False) -> None:
    if isinstance(value, Decimal):
        val_str = f"${value}"
    else:
        val_str = str(value)
    if bold:
        print(f"  {label:<35} {val_str:>15}")
    else:
        print(f"  {label:<35} {val_str:>15}")


def _pct(rate: Decimal) -> str:
    pct = rate * 100
    return f"{pct}%"


def _wrap(text: str, width: int) -> list[str]:
    """Simple word-wrap."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        lines.append(current)
    return lines
