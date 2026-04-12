# Credit Card Agreement Engine Trusted By The Courts

A pipeline that turns credit card agreements into executable, auditable simulations. Given a contract and statement history, the engine walks a judge through each billing cycle with deterministic, clause-referenced explanations of how every number was computed.

## What it does

**Input:** A credit card agreement (`.md`) + statement history (`.html`)

**Output:** Cycle-by-cycle interactive walkthrough showing:

- **2B. Interest Calculation** — step-by-step ADB method: daily balance table, formula, final amount
- **2C. Grace Period** — YES/NO with specific dates, payment amounts, and contract reasoning
- **2D. Fee Justification** — every fee with clause reference and trigger explanation
- **2E. Payment Waterfall** — Section 10 breakdown: collection costs, interest/fees, principal, excess to highest rate

All cycle explanations are **deterministic** — generated from templates and computed values, not LLM output. The LLM is used only once (Stage 1) to parse the contract into a structured IR. Everything after that is pure computation.

## Quick Start (7 steps)

**1. Environment**

```bash
python3 -m venv .venv && source .venv/bin/activate
```

**2. Install dependencies**

```bash
pip install -r requirements.txt
```

**3. Set up API key** (needed only for `analyze` command — not for `review`)

```bash
cp .env.example .env
# Edit .env with your Anthropic API key
```

**4. Parse a contract and walk through statements**

```bash
python -m engine analyze contracts/WesTex-VISA-credit-card-agreement.md
# When prompted, enter: fixtures/westex-visa-statements.html
# Press Enter to advance through cycles, 'b' to go back, 'q' to quit
```

**5. Reuse the IR without LLM** (instant, no API key needed)

```bash
python -m engine review engine/schemas/westex_ir.json -s fixtures/westex-visa-statements.html
```

**6. Verify determinism**

```bash
python -m engine decompile engine/schemas/westex_ir.json -o /tmp/run1.md
python -m engine decompile engine/schemas/westex_ir.json -o /tmp/run2.md
diff /tmp/run1.md /tmp/run2.md  # No output = identical
```

**7. Run tests**

```bash
python -m pytest engine/tests/test_scenarios.py -v
# 48 tests, all passing
```

## Commands

| Command | LLM | Purpose |
|---------|-----|---------|
| `analyze <contract.md>` | Yes (once) | Parse contract via LLM, then interactive walkthrough. Saves IR for reuse. |
| `review <ir.json> -s <statements.html>` | No | Load existing IR, interactive walkthrough. Instant. |
| `decompile <ir.json>` | No | IR to English (deterministic, verifiable). |
| `explain <statements.html>` | No | Non-interactive analysis, outputs HTML report. |

## Architecture

```
Contract.md ──LLM──> IR (JSON) ──deterministic──> English
                        │
                        ▼
Statements.html ───> Cycle Engine ───> Interactive Walkthrough
                        │                    │
                        │               2B. Interest (ADB)
                        │               2C. Grace Period
                        │               2D. Fee Justification
                        │               2E. Payment Waterfall
                        ▼
                  All computation is
                  deterministic — no LLM
```

**Stage 1: Contract → IR** (`parser.py`) — LLM extracts terms into a credit-card-specific JSON schema. APRs, fees, grace rules, payment waterfall order, default triggers, liability caps.

**Stage 2: IR → English** (`decompiler.py`) — Deterministic template engine. Same IR produces byte-identical English every run. No LLM.

**Stage 3: Statement Analysis** (`cycle_engine.py`, `adb.py`) — Processes each billing cycle against the contract rules. Tracks daily balances, computes ADB, evaluates grace periods, justifies fees, applies payment waterfall. All values match to the cent.

**Stage 4: Interactive Walkthrough** (`interactive.py`) — Presents results cycle-by-cycle with navigation. Every explanation sentence is generated from computed values via f-strings, not LLM.

## Where the LLM runs

| Module | LLM? | What it does |
|--------|------|-------------|
| `parser.py` | Yes | Contract `.md` → IR JSON (one call per contract) |
| `scenario_gen.py` | Yes | Generates sample scenarios for held-out contracts |
| Everything else | No | Pure Python computation and string formatting |

The LLM boundary is explicit: `parser.py` and `scenario_gen.py` import `anthropic`. No other module does.

## Test Coverage

48 tests across 12 scenarios, verifying:

- Interest calculation (grace active, grace lost, cash advance no-grace)
- Payment waterfall (two-bucket allocation, min to lowest rate, excess to highest)
- Fee assessment (late, returned, over-limit, foreign transaction)
- Minimum payment formula (8 edge cases)
- Grace period transitions (active → lost → trailing interest)
- Default triggers and account status
- Billing dispute state machine (valid, oral-only rejection)
- Unauthorized use liability (ATM $50 cap, VISA zero-liability)
- Authorized user revocation (both conditions required)
- Joint account withdrawal (future vs existing liability)

Validated against two complete 6-cycle statement histories:

- **WesTex Community Credit Union** (single-rate 12.9%) — all 12 values exact match
- **US Federal Credit Union** (dual-rate 17.99%/21.99%) — all 12 balances exact match

## File Structure

```
engine/
├── cli.py              Entry point and command routing
├── interactive.py      Interactive cycle-by-cycle walkthrough
├── account.py          Account state: balance buckets, disputes, liability
├── adb.py              Average Daily Balance tracker with changelog
├── events.py           40+ credit card event types as dataclasses
├── interest.py         Interest calculation (ADB method)
├── payments.py         Payment waterfall allocation (Section 10)
├── fees.py             Fee assessment (Section 7)
├── cycle_engine.py     Cycle-by-cycle analysis with explanations
├── simulator.py        Day-tick event-driven simulation
├── statement_input.py  Statement HTML parser
├── parser.py           Contract → IR (LLM, Stage 1)
├── scenario_gen.py     IR → scenario events (LLM, Stage 2)
├── decompiler.py       IR → English (deterministic, no LLM)
├── report.py           HTML report generator
├── terminal_report.py  Terminal output formatter
├── schemas/
│   └── westex_ir.json  Hand-crafted reference IR
└── tests/
    └── test_scenarios.py
```

## Limitations

- Credit card agreements only (not leases, procurement, etc.)
- Single combined ADB for single-rate agreements; dual-rate bucket tracking has minor cross-cycle drift
- Business day calendar not implemented (uses calendar days)
- Balance transfer intro period tracking is simplified
- Does not model cross-references between multiple agreements

## Approach and Design Choices

We chose depth over breadth: a professional-grade credit card simulator rather than a shallow generic contract engine. The engine computes real interest to the cent using the contract's exact daily periodic rates, not approximations. Every explanation is traceable to a specific contract clause.

The key insight is that credit card agreements are state machines: the account status, grace period eligibility, and balance buckets evolve deterministically based on events. The engine models this as a day-tick simulation where each event modifies state and the cycle-end checkpoint computes interest, evaluates grace, and generates the statement.

The separation between LLM (parsing) and computation (everything else) is a hard boundary. The LLM never sees statement data or produces explanations. This means the analysis is reproducible, auditable, and verifiable by a judge with a calculator.
