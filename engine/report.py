"""Generate judge-facing HTML explanation report from cycle results."""

from __future__ import annotations

from decimal import Decimal
from engine.cycle_engine import CycleResult, InterestExplanation, GracePeriodExplanation
from engine.statement_input import AccountParams, StatementHistory
from engine.adb import ADBEntry, ZERO


def generate_report(history: StatementHistory, results: list[CycleResult]) -> str:
    """Generate complete HTML report."""
    params = history.params
    sections = [_report_header(params)]

    for result in results:
        sections.append(_render_cycle(result, params))

    return _wrap_html(params, "\n".join(sections))


def _report_header(params: AccountParams) -> str:
    rates = f"APR for Purchases: {params.purchase_apr}%"
    if not params.single_rate:
        rates += f" | APR for Cash Advances: {params.cash_advance_apr}%"
    rates += f" | Daily Periodic Rate: {_pct(params.purchase_daily_rate)}"

    return f"""
<div class="agreement-ref" style="margin:20px auto; max-width:800px;">
  <strong>Account:</strong> {params.cardholder_name} | {params.account_number}<br>
  <strong>Credit Limit:</strong> ${params.credit_limit}<br>
  {rates}
</div>"""


def _render_cycle(r: CycleResult, params: AccountParams) -> str:
    start = r.cycle_start.strftime("%m/%d/%Y")
    end = r.cycle_end.strftime("%m/%d/%Y")
    month = r.cycle_start.strftime("%B %Y")

    parts = [f"""
<div class="statement" id="cycle-{r.cycle_number}">
  <div class="header">
    <h1>Cycle {r.cycle_number}: {month}</h1>
    <h2>Billing Period: {start} - {end} ({r.days_in_cycle} days)</h2>
  </div>

  <div class="summary-box">
    <div class="box"><div class="label">Previous Balance</div><div class="value">${r.previous_balance}</div></div>
    <div class="box"><div class="label">Payments</div><div class="value neg">-${r.total_payments}</div></div>
    <div class="box"><div class="label">Purchases</div><div class="value">${r.total_purchases}</div></div>
    <div class="box"><div class="label">Cash Advances</div><div class="value">${r.total_cash_advances}</div></div>
    <div class="box"><div class="label">Fees</div><div class="value">${r.total_fees}</div></div>
    <div class="box"><div class="label">Interest</div><div class="value">${r.total_interest}</div></div>
    <div class="box highlight"><div class="label">New Balance</div><div class="value">${r.new_balance}</div></div>
  </div>"""]

    # --- 2B: Interest Calculation ---
    parts.append(_render_interest(r, params))

    # --- 2C: Grace Period ---
    parts.append(_render_grace(r, params))

    # --- 2D: Fees ---
    parts.append(_render_fees(r))

    # --- 2E: Payment Waterfall ---
    parts.append(_render_payments(r, params))

    # Payment stub
    due_str = r.payment_due_date.strftime("%m/%d/%Y") if r.payment_due_date else "N/A"
    pct = params.minimum_payment_pct * 100
    floor = params.minimum_payment_floor
    pct_val = _round2(r.new_balance * params.minimum_payment_pct)

    parts.append(f"""
  <div class="payment-stub">
    <h3>Payment Information</h3>
    <table>
      <tr><td>New Balance</td><td class="amt"><strong>${r.new_balance}</strong></td></tr>
      <tr><td>Minimum Payment Due</td><td class="amt"><strong>${r.minimum_payment}</strong></td></tr>
      <tr><td>Payment Due Date</td><td class="amt"><strong>{due_str}</strong></td></tr>
    </table>
    <p class="small">Minimum payment = max({pct}% &times; ${r.new_balance}, ${floor}) = max(${pct_val}, ${floor}) = <strong>${r.minimum_payment}</strong></p>
  </div>
  <div class="meta">Statement {r.cycle_number} of {len([r])} | Billing Cycle: {start} - {end} | {r.days_in_cycle} days</div>
</div>""")

    return "\n".join(parts)


def _render_interest(r: CycleResult, params: AccountParams) -> str:
    ie = r.interest_explanation
    if not ie:
        return ""

    # Interest charge table
    rows = f"""
      <tr><td>Purchases</td><td class="amt">{_pct(ie.purchase_rate)}</td><td class="amt">{ie.purchase_apr}%</td>
          <td class="amt">${ie.purchase_adb}</td><td class="amt">{ie.days_in_cycle}</td><td class="amt">${ie.purchase_interest}</td></tr>
      <tr><td>Cash Advances</td><td class="amt">{_pct(ie.cash_advance_rate)}</td><td class="amt">{ie.cash_advance_apr}%</td>
          <td class="amt">${ie.cash_advance_adb}</td><td class="amt">{ie.days_in_cycle}</td><td class="amt">${ie.cash_advance_interest}</td></tr>"""

    grace_note = ""
    if r.grace_explanation:
        grace_note = f'<p class="small">Grace period in effect: {r.grace_explanation.reason}</p>'

    # ADB detail table
    adb_rows = ""
    total_days = 0
    total_subtotal = ZERO
    for entry in ie.adb_entries:
        s = entry.start_date.strftime("%m/%d")
        e = entry.end_date.strftime("%m/%d")
        adb_rows += f"""
        <tr><td>{s} - {e}</td><td class="amt">{entry.days}</td><td class="amt">${entry.daily_balance}</td>
            <td class="amt">${entry.subtotal}</td><td>{entry.activity}</td></tr>"""
        total_days += entry.days
        total_subtotal += entry.subtotal

    adb_note = ie.grace_note or ""
    interest_formula = ""
    if ie.total_interest > ZERO:
        interest_formula = f'= ${ie.purchase_adb} &times; {_pct(ie.purchase_rate)} &times; {ie.days_in_cycle}'

    return f"""
  <div class="section-label">2B. Interest Charge Calculation</div>
  <div class="interest-detail">
    <table>
      <thead><tr><th>Balance Type</th><th class="amt">Daily Periodic Rate</th><th class="amt">APR</th>
        <th class="amt">Balance Subject to Interest</th><th class="amt">Days in Cycle</th><th class="amt">Interest Charge</th></tr></thead>
      <tbody>{rows}</tbody>
      <tfoot><tr class="total-row"><td colspan="5">Total Interest Charged</td><td class="amt">${ie.total_interest}</td></tr></tfoot>
    </table>
    {grace_note}
  </div>

  <div class="section-label">Average Daily Balance Detail</div>
  <div class="adb-detail">
    <table>
      <thead><tr><th>Date Range</th><th class="amt">Days</th><th class="amt">Daily Balance</th><th class="amt">Subtotal</th><th>Activity</th></tr></thead>
      <tbody>{adb_rows}</tbody>
      <tfoot>
        <tr class="total-row"><td>Total</td><td class="amt">{total_days}</td><td></td><td class="amt">${_round2(total_subtotal)}</td><td></td></tr>
        <tr><td colspan="3"><strong>Average Daily Balance</strong></td><td class="amt"><strong>${ie.purchase_adb}</strong></td><td>{adb_note}</td></tr>
        <tr><td colspan="3"><strong>Interest</strong></td><td class="amt"><strong>${ie.total_interest}</strong></td><td>{interest_formula}</td></tr>
      </tfoot>
    </table>
  </div>"""


def _render_grace(r: CycleResult, params: AccountParams) -> str:
    if not r.grace_explanation:
        return ""
    ge = r.grace_explanation
    status_class = "grace-yes" if ge.eligible else "grace-no"
    return f"""
  <div class="section-label">2C. Grace Period Evaluation</div>
  <div class="{status_class}">
    <p>{ge.reason}</p>
    <p class="small">Per Agreement Section 6: Grace period of {params.grace_period_days} days applies if previous balance
    was paid in full by the due date, or there was no previous balance. Cash advances never have a grace period.</p>
  </div>"""


def _render_fees(r: CycleResult) -> str:
    if not r.fee_explanations:
        return f"""
  <div class="section-label">2D. Fee Justification</div>
  <div class="no-fees"><p>No fees assessed this cycle.</p></div>"""

    rows = ""
    for fe in r.fee_explanations:
        d = fe.fee_date.strftime("%m/%d")
        rows += f"""
      <tr class="fee-row"><td>{d}</td><td>{fe.description}</td><td>{fe.clause_ref}</td>
          <td class="amt">${fe.amount}</td></tr>
      <tr><td colspan="4" class="small" style="padding-left:20px;">{fe.justification}</td></tr>"""

    total = sum(f.amount for f in r.fee_explanations)
    return f"""
  <div class="section-label">2D. Fee Justification</div>
  <table>
    <thead><tr><th>Date</th><th>Description</th><th>Clause Reference</th><th class="amt">Amount</th></tr></thead>
    <tbody>{rows}</tbody>
    <tfoot><tr class="total-row"><td colspan="3">Total Fees</td><td class="amt">${_round2(total)}</td></tr></tfoot>
  </table>"""


def _render_payments(r: CycleResult, params: AccountParams) -> str:
    if not r.payment_explanations:
        return f"""
  <div class="section-label">2E. Payment Application (Clause 10)</div>
  <div class="no-fees"><p>No payments received this cycle.</p></div>"""

    parts = ["""<div class="section-label">2E. Payment Application (Clause 10)</div>"""]

    for pe in r.payment_explanations:
        d = pe.payment_date.strftime("%m/%d/%Y")
        rows = ""
        for step in pe.steps:
            rows += f"""
        <tr><td>{step.component}</td><td class="amt">${step.amount}</td><td>{step.applied_to}</td></tr>"""

        if pe.excess_amount > ZERO:
            rows += f"""
        <tr><td>Excess Above Minimum</td><td class="amt">${pe.excess_amount}</td><td>{pe.excess_applied_to}</td></tr>"""

        parts.append(f"""
  <div class="adb-detail">
    <p><strong>Payment of ${pe.total_amount} received {d}</strong></p>
    <table>
      <thead><tr><th>Payment Component</th><th class="amt">Amount</th><th>Applied To</th></tr></thead>
      <tbody>{rows}</tbody>
      <tfoot><tr class="total-row"><td>Total Payment Applied</td><td class="amt">${pe.total_amount}</td><td></td></tr></tfoot>
    </table>
    <p class="small">Per Agreement Section 10: Minimum payment applied first to collection costs, then interest/fees, then principal.
    Excess above minimum applied to highest-rate balance first.</p>
  </div>""")

    return "\n".join(parts)


def _wrap_html(params: AccountParams, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Credit Card Agreement Analysis Report</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Courier New', monospace; font-size: 13px; color: #1a1a1a; background: #fff; }}
  .statement {{ max-width: 800px; margin: 40px auto; padding: 32px; border: 2px solid #333; page-break-after: always; }}
  .header {{ border-bottom: 3px solid #003366; padding-bottom: 12px; margin-bottom: 16px; }}
  .header h1 {{ font-size: 18px; color: #003366; }}
  .header h2 {{ font-size: 13px; font-weight: normal; color: #555; }}
  .agreement-ref {{ background: #f0f0f0; padding: 8px 12px; margin: 12px 0; border-left: 4px solid #003366; font-size: 11px; }}
  .section-label {{ font-weight: bold; font-size: 13px; margin: 16px 0 6px 0; border-bottom: 1px solid #999; padding-bottom: 2px; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 12px; }}
  th, td {{ text-align: left; padding: 3px 8px; font-size: 12px; }}
  th {{ background: #e8e8e8; border-bottom: 1px solid #999; }}
  td {{ border-bottom: 1px solid #ddd; }}
  .amt {{ text-align: right; font-family: 'Courier New', monospace; }}
  .total-row {{ font-weight: bold; border-top: 2px solid #333; }}
  .neg {{ color: #006600; }}
  .fee-row {{ color: #990000; }}
  .summary-box {{ display: flex; justify-content: space-between; gap: 16px; margin: 12px 0; }}
  .summary-box .box {{ flex: 1; border: 1px solid #999; padding: 8px; text-align: center; }}
  .summary-box .box .label {{ font-size: 10px; color: #666; }}
  .summary-box .box .value {{ font-size: 16px; font-weight: bold; margin-top: 4px; }}
  .summary-box .highlight {{ background: #003366; color: #fff; }}
  .summary-box .highlight .label {{ color: #aaccee; }}
  .interest-detail {{ background: #f9f9f9; padding: 8px; margin: 8px 0; }}
  .interest-detail th {{ background: #dde4ec; }}
  .adb-detail {{ background: #f5f5f0; padding: 8px; margin: 8px 0; font-size: 11px; }}
  .adb-detail table td, .adb-detail table th {{ font-size: 11px; padding: 2px 6px; }}
  .payment-stub {{ border: 2px dashed #999; padding: 12px; margin-top: 16px; background: #fafafa; }}
  .payment-stub h3 {{ font-size: 13px; margin-bottom: 8px; }}
  .meta {{ font-size: 10px; color: #888; margin-top: 12px; text-align: center; }}
  .small {{ font-size: 11px; color: #555; margin-top: 4px; }}
  .grace-yes {{ background: #e8f5e9; padding: 8px; margin: 8px 0; border-left: 4px solid #4caf50; }}
  .grace-no {{ background: #fce4ec; padding: 8px; margin: 8px 0; border-left: 4px solid #e53935; }}
  .no-fees {{ background: #f5f5f5; padding: 8px; margin: 8px 0; color: #666; }}
</style>
</head>
<body>
<h1 style="text-align:center; padding:20px; color:#003366;">Credit Card Agreement Analysis Report</h1>
{body}
</body>
</html>"""


def _pct(rate: Decimal) -> str:
    """Format daily rate as percentage string like '0.035342%'."""
    pct = rate * 100
    return f"{pct}%"


def _round2(val: Decimal) -> Decimal:
    return val.quantize(Decimal("0.01"), rounding="ROUND_HALF_UP")
