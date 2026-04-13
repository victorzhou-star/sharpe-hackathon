# Credit Card Agreement Engine Trusted By The Courts

A system that turns credit card agreements into executable, auditable simulations. Given a contract and statement history, the engine walks a judge through each billing cycle with deterministic, clause-referenced explanations of how every number was computed.

## What it does

**Input:** A credit card agreement (`.md`) + statement history (`.html`)

**Output:** Cycle-by-cycle analysis showing, for each billing cycle:

- **2B. Interest Calculation** — daily balance table, ADB formula, rate application, final dollar amount
- **2C. Grace Period** — YES/NO with specific dates, payment amounts, and contract reasoning
- **2D. Fee Justification** — every fee with clause reference, trigger explanation, and contract evidence
- **2E. Payment Waterfall** — Section 10 breakdown: collection costs → interest/fees → principal → excess to highest rate

Every explanation links back to the specific contract clause that authorizes it. All cycle explanations are **deterministic** — generated from computed values and templates, not LLM output. The LLM is used only once to parse the contract into a structured IR.

## Two Interfaces

### Web Application

```bash
python -m web.app
# Open http://localhost:8000
```

- Create contract instances by uploading `.md` files (LLM parse) or `.json` IR files (no LLM)
- View extracted contract terms organized by section, or the full decompiled English
- Upload statement histories and browse cycle-by-cycle analysis
- Each section shows contract evidence linking the computation to the clause

### Terminal (Interactive)

```bash
# Parse contract via LLM, then walk through statements
python -m engine analyze contracts/WesTex-VISA-credit-card-agreement.md

# Reuse existing IR — instant, no LLM needed
python -m engine review engine/schemas/westex_ir.json -s fixtures/westex-visa-statements.html
```

Navigate cycles with Enter (next), `b` (back), `1-6` (jump), `q` (quit).

## Quick Start (7 steps)

**1. Environment**

```bash
python3 -m venv .venv && source .venv/bin/activate
```

**2. Install dependencies**

```bash
pip install -r requirements.txt
```

**3. Set up API key** (needed only for `analyze` command and web contract upload — not for `review`)

```bash
cp .env.example .env
# Edit .env with your Anthropic API key
```

**4. Run the web application**

```bash
python -m web.app
# Open http://localhost:8000
# Click "Load IR" → upload engine/schemas/westex_ir.json
# Click into the contract → "Analyze Statements" → upload fixtures/westex-visa-statements.html
# Browse cycles — each shows interest, grace, fees, payment waterfall with contract evidence
```

**5. Or use the terminal**

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

| Command | LLM | Interface | Purpose |
|---------|-----|-----------|---------|
| `python -m web.app` | Optional | Web | Full web UI at localhost:8000 |
| `analyze <contract.md>` | Yes (once) | Terminal | Parse contract via LLM, interactive walkthrough |
| `review <ir.json> -s <stmts>` | No | Terminal | Load existing IR, interactive walkthrough (instant) |
| `decompile <ir.json>` | No | Terminal | IR → English (deterministic, verifiable) |
| `explain <statements.html>` | No | Terminal | Non-interactive analysis |

## Architecture

```
                    ┌─────────── LLM boundary ───────────┐
                    │                                     │
Contract.md ──────> │  parser.py  ──> IR (JSON)           │
                    │                                     │
                    └─────────────────┬───────────────────┘
                                      │
                              ┌───────┴────────┐
                              │                │
                              ▼                ▼
                    Decompiler (deterministic)  Cycle Engine (deterministic)
                    IR ──> English              IR + Statements ──> Analysis
                              │                        │
                              │                   ┌────┴────┐
                              │                   │ For each │
                              │                   │  cycle:  │
                              │                   │ 2B Interest
                              │                   │ 2C Grace
                              │                   │ 2D Fees
                              │                   │ 2E Payments
                              │                   └─────────┘
                              │                        │
                              ▼                        ▼
                         English.md          Terminal / Web UI
                    (byte-identical          (with contract
                     every run)              evidence linking)
```

**Stage 1: Contract → IR** (`parser.py`) — LLM extracts terms into a credit-card-specific JSON schema: products, APR tiers, daily/monthly rates, fee schedule, grace period rules, payment waterfall order, default triggers, liability rules, dispute procedures.

**Stage 2: IR → English** (`decompiler.py`) — Deterministic template engine. Same IR produces byte-identical English every run. No LLM.

**Stage 3: Statement Analysis** (`cycle_engine.py`, `adb.py`) — Processes each billing cycle against the contract rules. Tracks daily balances, computes ADB (supporting both daily and monthly rate formulas), evaluates grace periods (including trailing interest), justifies fees, applies payment waterfall.

**Stage 4: Presentation** (`interactive.py`, `web/`) — Presents results with contract evidence linking: every computed value traces back to the specific contract clause that authorizes it.

## Where the LLM runs

| Module | LLM? | What it does |
|--------|------|-------------|
| `parser.py` | Yes | Contract `.md` → IR JSON (one call per contract) |
| `scenario_gen.py` | Yes | Generates sample scenarios for held-out contracts |
| Everything else | **No** | Pure Python computation and string formatting |

The LLM boundary is explicit: only `parser.py` and `scenario_gen.py` import `anthropic`. No other module does. The LLM never sees statement data or produces explanations.

## Test Coverage

48 tests across 12 scenarios, verifying:

- Interest calculation (grace active, grace lost, cash advance no-grace, monthly vs daily rates)
- Payment waterfall (two-bucket allocation, min to lowest rate, excess to highest)
- Fee assessment (late, returned, over-limit, foreign transaction, cash advance, card replacement)
- Minimum payment formula (8 edge cases)
- Grace period transitions (active → lost → trailing interest → restoration)
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
engine/                          Core engine (all deterministic except parser.py)
├── cli.py                       CLI entry point and command routing
├── interactive.py               Terminal cycle-by-cycle walkthrough
├── account.py                   Account state: balance buckets, disputes, liability
├── adb.py                       ADB tracker with changelog (daily + monthly rates)
├── events.py                    40+ credit card event types as dataclasses
├── interest.py                  Interest calculation
├── payments.py                  Payment waterfall allocation (Section 10)
├── fees.py                      Fee assessment (Section 7)
├── cycle_engine.py              Cycle-by-cycle analysis with explanations
├── simulator.py                 Day-tick event-driven simulation
├── statement_input.py           Statement HTML parser
├── parser.py                    Contract → IR (LLM, Stage 1)
├── scenario_gen.py              IR → scenario events (LLM, Stage 2)
├── decompiler.py                IR → English (deterministic, no LLM)
├── report.py                    HTML report generator
├── terminal_report.py           Terminal output formatter
├── schemas/westex_ir.json       Hand-crafted reference IR
└── tests/test_scenarios.py      48 tests, 132 assertions

web/                             Web application
├── app.py                       FastAPI backend (API + static files)
└── static/
    ├── index.html               Single-page app (all views + JS)
    └── style.css                Styles

contracts/                       Source contract files (.md)
fixtures/                        Test statement histories (.html)
```

## Limitations

- Credit card agreements only (not leases, procurement, etc.)
- Dual-rate bucket tracking has minor cross-cycle drift on interest (balances always exact)
- Business day calendar not implemented (uses calendar days)
- Balance transfer intro period tracking is simplified

## Approach and Design Choices

We chose depth over breadth: a professional-grade credit card simulator rather than a shallow generic contract engine. The engine computes real interest to the cent using the contract's exact periodic rates, not approximations. Every explanation is traceable to a specific contract clause.

The key insight is that credit card agreements are state machines: the account status, grace period eligibility, and balance buckets evolve deterministically based on events. The hardest part is the grace period — whether *this* cycle charges interest depends on whether the *previous* cycle had grace, because trailing interest from a prior cycle means paying the exact statement balance doesn't actually zero the account. We model this as: grace requires both that you paid in full AND that the previous cycle already had grace.

The separation between LLM (parsing) and computation (everything else) is a hard boundary. The LLM never sees statement data or produces explanations. This means the analysis is reproducible, auditable, and verifiable by a judge with a calculator.
