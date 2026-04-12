"""CLI entry point for the Credit Card Agreement Simulation Engine.

Usage:
    # Interactive: parse contract via LLM, then walkthrough statements
    python -m engine analyze contracts/WesTex-VISA-credit-card-agreement.md

    # Reuse existing IR (no LLM needed, instant)
    python -m engine review engine/schemas/westex_ir.json -s fixtures/westex-visa-statements.html

    # Decompile IR to English (deterministic, no LLM)
    python -m engine decompile engine/schemas/westex_ir.json
"""

from __future__ import annotations

import argparse
import json
import os

from dotenv import load_dotenv
load_dotenv()  # loads .env file into os.environ
import sys
from decimal import Decimal

from engine.simulator import simulate
from engine.decompiler import decompile_to_english
from engine.scenario_gen import hydrate_events


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)


def cmd_execute(args):
    """Execute a scenario against an IR."""
    with open(args.ir) as f:
        ir = json.load(f)

    with open(args.scenario) as f:
        raw_events = json.load(f)

    events = hydrate_events(raw_events)
    account = simulate(events, ir)

    # Print execution results
    print("=" * 70)
    print("EXECUTION RESULTS")
    print("=" * 70)
    print(f"Cardholder:      {account.cardholder_name}")
    print(f"Card Product:    {account.card_product}")
    print(f"Credit Limit:    ${account.credit_limit}")
    print(f"Account Status:  {account.status.value}")
    print(f"Final Balance:   ${account.total_balance}")
    print()

    for stmt in account.statements:
        print(f"--- Statement Cycle {stmt.cycle_number} (days {stmt.cycle_start_day}-{stmt.cycle_end_day}) ---")
        print(f"  Previous Balance:     ${stmt.previous_balance}")
        print(f"  Interest Charge:      ${stmt.total_interest}")
        print(f"    Purchase Interest:  ${stmt.purchase_interest}")
        print(f"    Cash Adv Interest:  ${stmt.cash_advance_interest}")
        print(f"    Bal Xfer Interest:  ${stmt.balance_transfer_interest}")
        print(f"  Total Payments:       ${stmt.total_payments}")
        print(f"  Late Fee:             ${stmt.late_fee}")
        print(f"  Over-Limit Fee:       ${stmt.over_limit_fee}")
        print(f"  New Balance:          ${stmt.new_balance}")
        print(f"  Minimum Payment:      ${stmt.minimum_payment}")
        print(f"  Due Day:              {stmt.payment_due_day}")
        print(f"  Grace Eligible:       {stmt.grace_period_eligible}")
        print()

    if account.default_triggers:
        print("DEFAULT TRIGGERS:")
        for dt in account.default_triggers:
            print(f"  {dt.name}: {dt.value}")
        print()

    if account.disputes:
        print("DISPUTES:")
        for d in account.disputes:
            print(f"  #{d.dispute_id}: ${d.amount} - {d.status.value}")
        print()

    if account.unauthorized_uses:
        print("UNAUTHORIZED USES:")
        for u in account.unauthorized_uses:
            print(f"  Day {u.day}: ${u.amount} ({u.tx_type}) - Liability: ${u.liability_assessed}")
        print()

    # Write full log to file
    if args.output:
        output = {
            "statements": [
                {
                    "cycle": s.cycle_number,
                    "days": f"{s.cycle_start_day}-{s.cycle_end_day}",
                    "previous_balance": str(s.previous_balance),
                    "interest": str(s.total_interest),
                    "purchase_interest": str(s.purchase_interest),
                    "cash_advance_interest": str(s.cash_advance_interest),
                    "payments": str(s.total_payments),
                    "late_fee": str(s.late_fee),
                    "over_limit_fee": str(s.over_limit_fee),
                    "new_balance": str(s.new_balance),
                    "minimum_payment": str(s.minimum_payment),
                    "due_day": s.payment_due_day,
                    "grace_eligible": s.grace_period_eligible,
                }
                for s in account.statements
            ],
            "final_status": account.status.value,
            "final_balance": str(account.total_balance),
            "defaults": [d.name for d in account.default_triggers],
            "log": account.log,
        }
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2, cls=DecimalEncoder)
        print(f"Full log written to {args.output}")


def cmd_decompile(args):
    """Decompile IR to English."""
    with open(args.ir) as f:
        ir = json.load(f)

    english = decompile_to_english(ir)

    if args.output:
        with open(args.output, "w") as f:
            f.write(english)
        print(f"English written to {args.output}")
    else:
        print(english)


def cmd_run(args):
    """Full pipeline: .md → IR → scenario → execution → English."""
    print(f"=== Stage 1: Parsing {args.contract} → IR ===")
    from engine.parser import parse_contract
    ir = parse_contract(args.contract)

    ir_path = args.contract.replace(".md", "_ir.json")
    with open(ir_path, "w") as f:
        json.dump(ir, f, indent=2)
    print(f"IR written to {ir_path}")

    print(f"\n=== Stage 2: Generating scenario from IR ===")
    from engine.scenario_gen import generate_scenario
    raw_events = generate_scenario(ir)

    scenario_path = args.contract.replace(".md", "_scenario.json")
    with open(scenario_path, "w") as f:
        json.dump(raw_events, f, indent=2)
    print(f"Scenario written to {scenario_path}")

    print(f"\n=== Stage 3: Executing scenario ===")
    events = hydrate_events(raw_events)
    account = simulate(events, ir)

    for stmt in account.statements:
        print(f"  Cycle {stmt.cycle_number}: balance=${stmt.new_balance}, "
              f"interest=${stmt.total_interest}, min=${stmt.minimum_payment}")

    log_path = args.contract.replace(".md", "_execution.json")
    output = {
        "statements": [
            {
                "cycle": s.cycle_number,
                "new_balance": str(s.new_balance),
                "interest": str(s.total_interest),
                "minimum_payment": str(s.minimum_payment),
                "grace_eligible": s.grace_period_eligible,
            }
            for s in account.statements
        ],
        "final_status": account.status.value,
        "final_balance": str(account.total_balance),
        "log": account.log,
    }
    with open(log_path, "w") as f:
        json.dump(output, f, indent=2, cls=DecimalEncoder)
    print(f"Execution log written to {log_path}")

    print(f"\n=== Stage 4: Decompiling IR → English ===")
    english = decompile_to_english(ir)
    english_path = args.contract.replace(".md", "_english.md")
    with open(english_path, "w") as f:
        f.write(english)
    print(f"English written to {english_path}")

    # Verify determinism
    english2 = decompile_to_english(ir)
    print(f"Determinism check: {'PASS' if english == english2 else 'FAIL'}")


def cmd_explain(args):
    """Analyze statement history and produce explanation report."""
    from engine.statement_input import parse_statement_html
    from engine.cycle_engine import run_cycles
    from engine.report import generate_report

    print(f"=== Parsing statement history: {args.statements} ===")
    history = parse_statement_html(args.statements)

    print(f"  Cardholder: {history.params.cardholder_name}")
    print(f"  Account:    {history.params.account_number}")
    print(f"  Credit Limit: ${history.params.credit_limit}")
    print(f"  Purchase APR: {history.params.purchase_apr}%")
    if not history.params.single_rate:
        print(f"  Cash Advance APR: {history.params.cash_advance_apr}%")
    print(f"  Cycles found: {len(history.cycles)}")

    for c in history.cycles:
        print(f"    Cycle {c.cycle_number}: {c.cycle_start} to {c.cycle_end} "
              f"({c.days_in_cycle} days) — {len(c.transactions)} transactions")

    print(f"\n=== Running cycle analysis ===")
    results = run_cycles(history)

    for r in results:
        grace = "YES" if r.grace_explanation and r.grace_explanation.eligible else "NO"
        print(f"  Cycle {r.cycle_number}: balance=${r.new_balance}, "
              f"interest=${r.total_interest}, grace={grace}, fees=${r.total_fees}")

    print(f"\n=== Generating explanation report ===")
    report_html = generate_report(history, results)

    output_path = args.output
    if not output_path:
        output_path = args.statements.replace(".html", "_analysis.html")
    with open(output_path, "w") as f:
        f.write(report_html)
    print(f"Report written to {output_path}")
    print(f"Open in browser: file://{output_path}")

    print(f"\n=== Analysis complete ===")


def cmd_analyze(args):
    """Interactive analysis: parse contract via LLM, show IR, walkthrough."""
    from engine.interactive import run_interactive
    run_interactive(contract_path=args.contract,
                    statements_path=getattr(args, 'statements', None))


def cmd_review(args):
    """Interactive walkthrough using existing IR (no LLM)."""
    from engine.interactive import run_interactive
    run_interactive(ir_path=args.ir,
                    statements_path=getattr(args, 'statements', None))


def main():
    parser = argparse.ArgumentParser(
        description="WesTex VISA Credit Card Simulation Engine")
    subparsers = parser.add_subparsers(dest="command")

    # execute
    p_exec = subparsers.add_parser("execute",
                                   help="Run scenario against IR")
    p_exec.add_argument("--ir", required=True, help="Path to IR JSON")
    p_exec.add_argument("--scenario", required=True, help="Path to scenario JSON")
    p_exec.add_argument("--output", "-o", help="Path for execution log output")

    # decompile
    p_dec = subparsers.add_parser("decompile",
                                  help="Convert IR to English (deterministic)")
    p_dec.add_argument("ir", help="Path to IR JSON")
    p_dec.add_argument("--output", "-o", help="Path for English output")

    # run (full pipeline)
    p_run = subparsers.add_parser("run",
                                  help="Full pipeline: .md → IR → scenario → execute → English")
    p_run.add_argument("contract", help="Path to contract .md file")

    # explain (statement history analysis — no LLM)
    p_explain = subparsers.add_parser("explain",
                                      help="Analyze statement history against contract rules (no LLM)")
    p_explain.add_argument("statements", help="Path to statement history HTML")
    p_explain.add_argument("--output", "-o", help="Path for HTML report output")

    # analyze (interactive: contract.md → LLM → IR → walkthrough)
    p_analyze = subparsers.add_parser("analyze",
                                      help="Parse contract via LLM, then interactive walkthrough")
    p_analyze.add_argument("contract", help="Path to contract .md file")
    p_analyze.add_argument("--statements", "-s", help="Path to statement history HTML (skip prompt)")

    # review (interactive: existing IR.json → walkthrough, NO LLM)
    p_review = subparsers.add_parser("review",
                                     help="Load existing IR and walkthrough statements (no LLM)")
    p_review.add_argument("ir", help="Path to IR .json file (from a prior analyze run)")
    p_review.add_argument("--statements", "-s", help="Path to statement history HTML (skip prompt)")

    args = parser.parse_args()

    if args.command == "execute":
        cmd_execute(args)
    elif args.command == "decompile":
        cmd_decompile(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "explain":
        cmd_explain(args)
    elif args.command == "analyze":
        cmd_analyze(args)
    elif args.command == "review":
        cmd_review(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
