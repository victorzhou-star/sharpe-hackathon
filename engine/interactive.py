"""Interactive cycle-by-cycle walkthrough for a judge.

Flow:
  1. Parse contract → IR (LLM)
  2. Show contract terms (deterministic)
  3. Prompt for statement history file
  4. Process cycles
  5. Walk through one cycle at a time — Enter to advance, b to go back, q to quit
"""

from __future__ import annotations

import os
import sys
import json
import shutil
from decimal import Decimal

from engine.adb import ZERO


def run_interactive(contract_path: str = None, ir_path: str = None,
                    statements_path: str = None) -> None:
    """Main interactive entry point.

    Two modes:
      1. contract_path given (.md) → LLM parses contract into IR, then walkthrough
      2. ir_path given (.json)     → Load existing IR directly (no LLM), then walkthrough
    """
    W = min(shutil.get_terminal_size().columns, 80)

    _banner(W)

    # ------------------------------------------------------------------
    # Stage 1: Get IR (either parse contract via LLM or load existing)
    # ------------------------------------------------------------------
    if ir_path and os.path.exists(ir_path):
        # Load existing IR — no LLM needed
        _stage(1, "Loading pre-built IR (no LLM)", W)
        print(f"  Source: {ir_path}")
        with open(ir_path, "r") as f:
            ir = json.load(f)
        _ok("IR loaded.")
        print()
    elif contract_path:
        # Parse contract via LLM
        _stage(1, "Parsing contract into IR (via LLM)...", W)
        print(f"  Source: {contract_path}")

        from engine.parser import parse_contract
        ir = parse_contract(contract_path)
        _ok("Contract parsed successfully.")
        print()

        # Save IR for future reuse
        saved_ir_path = contract_path.replace(".md", "_ir.json")
        with open(saved_ir_path, "w") as f:
            json.dump(ir, f, indent=2)
        _dim(f"  IR saved to {saved_ir_path}")
        _dim(f"  (Reuse with: python -m engine review {saved_ir_path} -s <statements>)")
        print()
    else:
        print("  Error: provide either a contract .md or an IR .json")
        return

    # ------------------------------------------------------------------
    # Stage 2: Show contract terms (deterministic — no LLM)
    # ------------------------------------------------------------------
    _stage(2, "Contract Terms (deterministic decompilation)", W)
    _print_ir_summary(ir, W)
    print()

    # Decompile to English
    from engine.decompiler import decompile_to_english
    english = decompile_to_english(ir)
    english2 = decompile_to_english(ir)
    _dim(f"  Determinism check: {'PASS' if english == english2 else 'FAIL'}")
    print()

    # ------------------------------------------------------------------
    # Stage 3: Prompt for statement history
    # ------------------------------------------------------------------
    _stage(3, "Statement History Input", W)
    print()

    if statements_path and os.path.exists(statements_path):
        stmt_path = statements_path
        print(f"  Using: {stmt_path}")
    else:
        stmt_path = _prompt("  Enter path to statement history HTML: ")
        if not stmt_path or not os.path.exists(stmt_path):
            print(f"  File not found: {stmt_path}")
            return

    # ------------------------------------------------------------------
    # Stage 4: Process cycles
    # ------------------------------------------------------------------
    print()
    _stage(4, "Processing statement history...", W)

    from engine.statement_input import parse_statement_html
    from engine.cycle_engine import run_cycles

    history = parse_statement_html(stmt_path)
    results = run_cycles(history)
    params = history.params

    print(f"  Cardholder:  {params.cardholder_name}")
    print(f"  Account:     {params.account_number}")
    print(f"  Cycles:      {len(results)}")
    print()

    _ok(f"Ready. {len(results)} billing cycles to review.")
    print()

    # ------------------------------------------------------------------
    # Stage 5: Interactive walkthrough
    # ------------------------------------------------------------------
    _prompt("  Press Enter to begin walkthrough...")
    print()

    idx = 0
    while 0 <= idx < len(results):
        _clear_soft()
        _print_cycle_full(results[idx], history.cycles[idx], params, idx + 1, len(results), W)

        if idx == len(results) - 1:
            # Last cycle — show summary too
            _print_summary(results, params, W)
            nav = _prompt("\n  [b] back  [q] quit  > ")
        else:
            nav = _prompt(f"\n  [Enter] next  [b] back  [q] quit  [1-{len(results)}] jump  > ")

        nav = nav.strip().lower()
        if nav == "q":
            break
        elif nav == "b":
            idx = max(0, idx - 1)
        elif nav.isdigit():
            jump = int(nav)
            if 1 <= jump <= len(results):
                idx = jump - 1
            else:
                idx += 1
        else:
            idx += 1

    print()
    _dim("  Session ended.")
    print()


# ===================================================================
# Cycle printer
# ===================================================================

def _print_cycle_full(r, cd, params, num, total, W):
    """Print one cycle with all four explanation sections."""
    month = r.cycle_start.strftime("%B %Y")
    start = r.cycle_start.strftime("%m/%d/%Y")
    end = r.cycle_end.strftime("%m/%d/%Y")

    # Header
    print(f"  {'=' * (W - 4)}")
    print(f"  CYCLE {num} of {total}: {month}")
    print(f"  {start} — {end}  ({r.days_in_cycle} days)")
    print(f"  {'=' * (W - 4)}")
    print()

    # Summary bar
    print(f"  Previous Balance     ${r.previous_balance:>10}")
    print(f"  + Purchases          ${r.total_purchases:>10}")
    print(f"  + Cash Advances      ${r.total_cash_advances:>10}")
    print(f"  + Fees               ${r.total_fees:>10}")
    print(f"  + Interest           ${r.total_interest:>10}")
    print(f"  - Payments           ${r.total_payments:>10}")
    print(f"  {'-' * 40}")
    print(f"  NEW BALANCE          ${r.new_balance:>10}")
    due = r.payment_due_date.strftime("%m/%d/%Y") if r.payment_due_date else "N/A"
    print(f"  Min Payment: ${r.minimum_payment}  |  Due: {due}")
    print()

    # Transactions
    if cd.transactions:
        print(f"  TRANSACTIONS")
        print(f"  {'-' * 68}")
        for tx in sorted(cd.transactions, key=lambda t: t.post_date):
            d = tx.post_date.strftime("%m/%d")
            sign = "-" if tx.category == "Payment" else " "
            desc = tx.description[:35].ljust(35)
            cat = tx.category[:10].ljust(10)
            print(f"  {d}  {cat}  {desc}  {sign}${tx.amount:>9}")
        print()

    # 2B: Interest
    _print_2b(r, params, W)

    # 2C: Grace
    _print_2c(r, params, W)

    # 2D: Fees
    _print_2d(r, W)

    # 2E: Payment waterfall
    _print_2e(r, params, W)


def _print_2b(r, params, W):
    ie = r.interest_explanation
    if not ie:
        return

    grace_active = r.grace_explanation and r.grace_explanation.eligible

    _section("2B", f"Interest Charged: ${ie.total_interest}", W)

    if grace_active and ie.total_interest == ZERO:
        # Grace is active — interest is $0. Show simple explanation.
        print()
        print(f"  Grace period is in effect (see 2C below). Purchases have")
        print(f"  at least {params.grace_period_days} days from the statement date before interest")
        print(f"  accrues. Because the grace period applies, the Average Daily")
        print(f"  Balance is NOT used to compute interest this cycle.")
        print()
        if ie.adb_entries:
            _dim(f"  (For reference, the ADB if grace were not in effect would be ${ie.purchase_adb}")
            total_sub = sum(e.subtotal for e in ie.adb_entries)
            total_days = sum(e.days for e in ie.adb_entries)
            _dim(f"   computed as ${total_sub} / {total_days} days — but this is not applied.)")
        print()
        return

    # Grace NOT active — show full ADB breakdown with step-by-step formula
    print()
    print(f"  No grace period this cycle. Interest is computed using the")
    print(f"  Average Daily Balance (ADB) method per Section 6:")
    print()

    # Explain what the opening balance is
    opening = ie.adb_entries[0].daily_balance if ie.adb_entries else ZERO
    if opening > ZERO:
        print(f"  The cycle opens with a carried balance of ${opening} from the")
        print(f"  previous cycle. New transactions are added to (or subtracted")
        print(f"  from) this running balance. Interest accrues on the TOTAL")
        print(f"  daily balance — not just this month's new charges.")
        print()

    print(f"  Step 1: Track the daily balance through the cycle")
    print()

    total_days = 0
    total_sub = ZERO

    if ie.adb_entries:
        print(f"  {'Date Range':<16} {'Days':>5}  {'Daily Balance':>14}  {'Bal x Days':>12}  Activity")
        print(f"  {'-' * 70}")
        for e in ie.adb_entries:
            s = e.start_date.strftime("%m/%d")
            ed = e.end_date.strftime("%m/%d")
            print(f"  {s}-{ed:<10}  {e.days:>5}  ${e.daily_balance:>13}  ${e.subtotal:>11}  {e.activity}")
            total_days += e.days
            total_sub += e.subtotal
        print(f"  {'-' * 70}")
        print(f"  {'':>16} {total_days:>5}  {'Sum(Bal x Days)':>14}  ${total_sub:>11}")
        print()

    # Formula — step by step
    adb = ie.purchase_adb if ie.purchase_adb > ZERO else ie.cash_advance_adb

    if adb > ZERO:
        print(f"  Step 2: Compute the Average Daily Balance")
        print(f"  ADB = Sum(Bal x Days) / Days in Cycle")
        print(f"      = ${total_sub} / {total_days}")
        print(f"      = ${adb}")
        print()

    if ie.total_interest > ZERO:
        rate = ie.purchase_rate if ie.purchase_interest > ZERO else ie.cash_advance_rate
        rate_pct = rate * 100
        rt = getattr(ie, 'rate_type', 'daily')
        if rt == "monthly":
            print(f"  Step 3: Apply the monthly periodic rate")
            print(f"  Interest = ADB x Monthly Rate")
            print(f"           = ${adb} x {rate_pct}%")
            print(f"           = ${ie.total_interest}")
        else:
            print(f"  Step 3: Apply the daily periodic rate")
            print(f"  Interest = ADB x Daily Rate x Days")
            print(f"           = ${adb} x {rate_pct}% x {ie.days_in_cycle}")
            print(f"           = ${ie.total_interest}")
    else:
        print(f"  Interest = $0.00")

    # Show both buckets if dual-rate with actual interest
    if not params.single_rate and (ie.purchase_interest > ZERO or ie.cash_advance_interest > ZERO):
        print()
        print(f"  Per-bucket breakdown (different APRs apply):")
        print(f"  {'Bucket':<20} {'APR':>8} {'ADB':>12} {'Interest':>10}")
        print(f"  {'-' * 52}")
        print(f"  {'Purchases':<20} {ie.purchase_apr:>7}% ${ie.purchase_adb:>11} ${ie.purchase_interest:>9}")
        print(f"  {'Cash Advances':<20} {ie.cash_advance_apr:>7}% ${ie.cash_advance_adb:>11} ${ie.cash_advance_interest:>9}")
        print(f"  {'-' * 52}")
        print(f"  {'Total':<20} {'':>8} {'':>12} ${ie.total_interest:>9}")

    print()


def _print_2c(r, params, W):
    ge = r.grace_explanation
    if not ge:
        return

    status = "YES" if ge.eligible else "NO"
    _section("2C", f"Grace period: {status}", W)

    for line in _wrap(ge.reason, W - 6):
        print(f"  {line}")
    print()
    _dim(f"  [Section 6: {params.grace_period_days}-day grace on purchases if previous")
    _dim(f"   balance paid in full. Cash advances: never.]")
    print()


def _print_2d(r, W):
    total_fees = sum((f.amount for f in r.fee_explanations), ZERO) if r.fee_explanations else ZERO
    if total_fees > ZERO:
        _section("2D", f"Fees Charged: ${total_fees}", W)
    else:
        _section("2D", "Fees Charged: $0.00", W)

    if not r.fee_explanations:
        _dim("  No fees this cycle.")
        print()
        return

    for fe in r.fee_explanations:
        d = fe.fee_date.strftime("%m/%d/%Y")
        print(f"  {d}  {fe.description:<30}  ${fe.amount:>8}")
        _dim(f"         Clause: {fe.clause_ref}")
        for line in _wrap(fe.justification, W - 12):
            _dim(f"         {line}")
        print()


def _print_2e(r, params, W):
    total_paid = sum((pe.total_amount for pe in r.payment_explanations), ZERO) if r.payment_explanations else ZERO
    if total_paid > ZERO:
        _section("2E", f"Payments Applied: ${total_paid}", W)
    else:
        _section("2E", "Payments Applied: $0.00", W)

    if not r.payment_explanations:
        _dim("  No payments this cycle.")
        print()
        return

    for pe in r.payment_explanations:
        d = pe.payment_date.strftime("%m/%d/%Y")
        print(f"  Payment: ${pe.total_amount} on {d}")
        print()
        print(f"  {'Step':<36} {'Amount':>10}  Applied To")
        print(f"  {'-' * 66}")
        for step in pe.steps:
            print(f"  {step.component:<36} ${step.amount:>9}  {step.applied_to}")
        if pe.excess_amount > ZERO:
            print(f"  {'Excess (to highest rate)':<36} ${pe.excess_amount:>9}  {pe.excess_applied_to}")
        print(f"  {'-' * 66}")
        print(f"  {'Total':<36} ${pe.total_amount:>9}")
        print()


def _print_summary(results, params, W):
    """Print summary table after last cycle."""
    print()
    print(f"  {'=' * (W - 4)}")
    print(f"  ANALYSIS COMPLETE — SUMMARY")
    print(f"  {'=' * (W - 4)}")
    print()

    print(f"  {'Cycle':<8} {'Month':<12} {'Balance':>10} {'Interest':>10} {'Fees':>8} {'Grace':>6}")
    print(f"  {'-' * 58}")
    ti = ZERO
    tf = ZERO
    for r in results:
        m = r.cycle_start.strftime("%b %Y")
        g = "YES" if r.grace_explanation and r.grace_explanation.eligible else "NO"
        print(f"  {r.cycle_number:<8} {m:<12} ${r.new_balance:>9} ${r.total_interest:>9} ${r.total_fees:>7} {g:>6}")
        ti += r.total_interest
        tf += r.total_fees
    print(f"  {'-' * 58}")
    print(f"  {'TOTAL':<20} {'':>10} ${ti:>9} ${tf:>7}")
    print()
    final = results[-1].new_balance
    print(f"  Final Balance:       ${final}")
    print(f"  Total Interest Paid: ${ti}")
    print(f"  Total Fees Paid:     ${tf}")
    print()


# ===================================================================
# IR Summary (deterministic)
# ===================================================================

def _print_ir_summary(ir: dict, W: int) -> None:
    """Show key terms from the parsed IR."""
    meta = ir.get("meta", {})
    interest = ir.get("interest", {})
    grace = ir.get("grace_period", {})
    mp = ir.get("minimum_payment", {})
    fees = ir.get("fees", {})
    default_triggers = ir.get("default_triggers", [])
    pa = ir.get("payment_application", {})
    liab = ir.get("liability", {})

    print(f"  Issuer:          {meta.get('issuer_name', 'N/A')}")
    print(f"  Network:         {meta.get('network', 'N/A')}")
    print(f"  Governing Law:   {meta.get('governing_law_state', 'N/A')}")
    print()

    # Rates
    rates = interest.get("daily_periodic_rates", [])
    if rates:
        print(f"  Interest Rates (Section 6):")
        for r in rates:
            print(f"    APR {r.get('apr', '?')}%  →  daily {r.get('daily_rate', '?')}")
        print(f"    Method: {interest.get('method', 'N/A').replace('_', ' ')}")
    print()

    # Grace
    print(f"  Grace Period (Section 6):")
    print(f"    Purchases:      {grace.get('purchases_days', 'N/A')} days")
    print(f"    Cash Advances:  {grace.get('cash_advances', 'none')}")
    print(f"    Condition:      previous balance paid in full by due date")
    print()

    # Minimum Payment
    print(f"  Minimum Payment (Section 5):")
    print(f"    {mp.get('percent_of_balance', '?')}% of balance or ${mp.get('floor_amount', '?')}, whichever greater")
    print(f"    If balance <= ${mp.get('pay_in_full_threshold', '?')}: pay in full")
    print()

    # Fees
    print(f"  Fees (Section 7):")
    lp = fees.get("late_payment", {})
    if isinstance(lp, dict):
        print(f"    Late Payment:      ${lp.get('amount', '?')}")
    rp = fees.get("returned_payment", {})
    if isinstance(rp, dict):
        print(f"    Returned Payment:  ${rp.get('amount', '?')} (capped at min payment)")
    ol = fees.get("over_limit", {})
    if isinstance(ol, dict):
        print(f"    Over Limit:        ${ol.get('amount', '?')} (recurring monthly)")
    ftf = fees.get("foreign_transaction_pct", "?")
    print(f"    Foreign Txn:       {ftf}%")
    print()

    # Payment Waterfall
    print(f"  Payment Application (Section 10):")
    order = pa.get("minimum_payment_order", [])
    for i, step in enumerate(order, 1):
        print(f"    {i}. {step.replace('_', ' ')}")
    print(f"    Excess: {pa.get('excess_payment_order', 'highest rate first').replace('_', ' ')}")
    print()

    # Default triggers
    if default_triggers:
        print(f"  Default Triggers (Section 11):")
        for dt in default_triggers:
            print(f"    {dt.get('code', '?')}: {dt.get('condition', '?').replace('_', ' ')}")
    print()

    # Unauthorized use
    if liab:
        print(f"  Unauthorized Use (Section 9):")
        print(f"    Liability cap:     ${liab.get('unauthorized_use_cap', '?')}")
        print(f"    VISA zero-liability: {liab.get('visa_zero_liability', False)}")
        exc = liab.get("zero_liability_exceptions", [])
        if exc:
            print(f"    Exceptions:        {', '.join(e.replace('_', ' ') for e in exc)}")
    print()


# ===================================================================
# Terminal helpers
# ===================================================================

def _banner(W):
    print()
    print(f"  {'=' * (W - 4)}")
    print(f"  CREDIT CARD AGREEMENT SIMULATION ENGINE")
    print(f"  Executable Contracts — Sharpe Hackathon")
    print(f"  {'=' * (W - 4)}")
    print()


def _stage(n, label, W):
    print(f"  [{n}] {label}")
    print(f"  {'-' * (W - 4)}")


def _section(code, label, W):
    """Print a prominent section header with result on the same line."""
    line = f"  {code}. {label}"
    print()
    print(f"\033[1m{line}\033[0m")  # bold
    print(f"  {'─' * (W - 4)}")


def _ok(msg):
    print(f"  \033[32m✓\033[0m {msg}")


def _dim(msg):
    print(f"\033[90m{msg}\033[0m")


def _prompt(msg):
    try:
        return input(msg)
    except (EOFError, KeyboardInterrupt):
        print()
        return "q"


def _clear_soft():
    """Print some blank lines to visually separate cycles."""
    print("\n" * 2)


def _wrap(text: str, width: int) -> list[str]:
    words = text.replace("\n", " ").split()
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
