# Sharpe Hackathon Track: Executable Contracts

## Overview

Contracts cover a lot: procurement, credit, leases, employment, and more. They are mostly plain text, and enforcing them usually means lawyers and courts. This track asks whether a machine can read a contract and actually run it.

You build a pipeline that turns real legal contracts into a representation a computer can interpret, enforce, and run, and that can be turned back into readable English.

**What you ship.** Judges expect something they can run: an executable representation (or a program that builds and runs it), plus a deterministic path from that representation back to English. A pretty parse tree that never evaluates interest, deadlines, or breach conditions will score poorly on **Executability** even if the data model looks impressive.

**Why it is awkward in practice.** Natural language mixes rules, exceptions, cross-references, and defined terms. Dates interact with business days and grace periods. Money flows depend on prior events. A hackathon-sized system will not capture every corner case; the goal is to show real computation and honest limits, not to pretend the contract is fully formalized.

## The challenge

### Part 1: Contract → code

**Input.** Contracts arrive as **Markdown** (`.md`), in the same spirit as the sample files in this repository. Build around that unless you document a preprocessing step clearly.

From natural language, produce a structured, executable form the machine can run. You should be able to:

- Parse clauses and pull out obligations, conditions, deadlines, and penalties
- Put those into a machine-executable format
- Run the logic: evaluate conditions, apply obligations, compute payments, enforce constraints

How you get there is up to you. Examples people use:

- A domain-specific language (DSL) for contracts
- Structured data (JSON, YAML, or similar) plus a runtime
- A library or framework in a general-purpose language (Python, TypeScript, Solidity, etc.)
- A visual or graph model with an execution engine
- An AI-assisted pipeline that extracts and compiles contract logic

**What "run" means.** You define that; judges favor work that does real computation and stateful reasoning, not only static structure. Patterns that often work:

- **Scenario-based evaluation:** fix a timeline of facts (dates, payments, notices, deliveries) and compute outcomes, amounts due, or breach status.
- **Stateful simulation:** carry balances, deadlines, and obligation status forward as inputs change.
- **Event-driven stepping:** apply events (e.g. default, cure period started, invoice received) and observe how contract logic updates.
- **Formula and constraint evaluation:** encode interest, fees, rent steps, or caps as expressions over inputs.
- **Time-aware logic:** model calendar or business days, grace periods, and expirations where the sample contract depends on them.

You can combine these or invent something different.

**Execution data (facts and scenarios).** The contract Markdown only encodes the rules. To actually *run* them you also need **data**: dates, balances, payments, notices, deliveries, events (e.g. default, cure started), party actions, or whatever your model requires. Your demo should make it obvious **what inputs** you fed in and **what the engine produced** from those inputs. If output appears with no visible scenario data, judges cannot tell whether anything was really executed.

**LLMs to generate sample data (required for generality).** Your pipeline should include a step that uses a **large language model** to propose or fill in **scenario data** (structured facts, events, timelines, or similar) so the executor can run. Organizers will **not** provide hand-written fixtures for the **held-out** contracts. If you only ever use manually authored JSON for the public samples, your system may not run on unseen Markdown at evaluation time. The LLM step is for **scenario generation** (or equivalent), not for **executable → English** (that path stays LLM-free; see Part 2). Document where the LLM runs, what it outputs, and how that data feeds the runner.

### Part 2: Code → English

Whatever you build must compile **back to English**. The regenerated text does not need to match the original word for word, but it must:

- Keep the legal meaning and intent of each clause
- Read clearly for someone who is not an engineer
- Include obligations, conditions, and terms from the executable representation

**Deterministic English; no LLMs on this step.** The path from your **executable representation to English** must be **deterministic**: same executable, same English every time (no randomness, temperature, or sampling). **Do not use large language models** on executable → English. LLMs elsewhere are fine, including **generating scenario/sample data** so you can run on held-out contracts (see **Execution data**), plus parsing natural language into your IR, suggesting structure, and tooling, as long as **executable → English** is a normal program: templates, grammars, pretty-printers, etc. Say briefly how judges can check determinism (module boundaries, no LLM in the decompiler, how to re-run and diff).

**Traceability** (links from original clauses to IR to regenerated English) is optional but can help a submission.

**Completeness and fidelity** means the English matches what your executable encodes (for hackathon scope). Judges **do not** grade court-ready legal accuracy. **Not** legal advice.

The round-trip (English → executable → English) is required.

## Example contracts

Sample files live at the repo root; filenames match the table. Use them to develop and test.

**Provenance.** These examples were sourced from [Law Insider](https://www.lawinsider.com), which has many other real contract texts worth browsing if you want more material to experiment with. For this repository they were converted to Markdown and cleaned up. Anything that was blacked out or omitted in the originals was replaced with **fake** placeholder text (names, amounts, addresses, and similar details are not real).

| Contract                                                          | Type                  | Complexity                                       |
| ----------------------------------------------------------------- | --------------------- | ------------------------------------------------ |
| `WesTex-VISA-credit-card-agreement.md`                            | Credit card agreement | Medium: interest, fees, payment logic            |
| `ORBCOMM-Orbital-amendment-1-AIS-payload-procurement-2006.md`     | Procurement amendment | High: milestones, delivery, warranty             |
| `Galleria-Atlanta-office-lease-American-Safety-Insurance-2006.md` | Office lease          | High: rent escalation, maintenance, termination  |
| `Masterworks084-IndieBrokers-Regulation-A-engagement-letter.md`   | Engagement letter     | Medium: compensation, regulatory conditions      |
| `A-Plus-Xodtec-securities-exchange-agreement-2009.md`             | Securities exchange   | Medium: exchange conditions, reps and warranties |


You are not limited to these. The system should generalize beyond them.

**Suggested starting point.** If you want one file to debug parsing and execution before tackling cross-references everywhere, the engagement letter or credit card agreement is often easier to reason about than a long lease or procurement amendment. That is a suggestion, not a rule.

**Held-out evaluation.** Organizers use a **separate set** of Markdown contracts that are **not** in this repo. **Judges evaluate each submission by running it on the same set of held-out Markdown contracts** (one shared evaluation set for everyone, not a different bundle per team). There are **no** bundled scenario files for those documents; your pipeline must still produce runnable inputs, which is why the **LLM-based sample-data step** (above) is part of the expected design. Treat the published samples as dev and demo material; aim for robustness on unseen `.md`, not memorizing these files.

You may use the bundled `.md` files in this repo for development, demos, and your submission. They are **illustrative only** and **not** legal advice. If you republish contract text outside this event, follow copyright and [Law Insider](https://www.lawinsider.com) terms.

## Requirements

- **Input:** Markdown (`.md`) contract text, consistent with the samples
- Accept at least one provided sample as input and produce a working executable output
- Include an **LLM step that generates sample/scenario data** (or equivalent) so execution can run on **arbitrary** contract Markdown, including **held-out** contracts that do not ship with hand-written fixtures (see **Execution data** under Part 1)
- The executable representation must actually **run** on **concrete scenario data** (facts, events, amounts, dates, or equivalent): show what you passed in, that the engine evaluated conditions / computed values / enforced terms, and what came out. The contract Markdown alone is not enough to demonstrate that (see **Execution data** under Part 1)
- The representation must compile back to English that preserves meaning; **executable → English** must be **deterministic** and **must not use LLMs** (see Part 2)
- Include a demo of the full round-trip: English → executable → English
- **Base demo:** runnable and checkable in **fewer than 10 steps** — document a numbered list (README or notebook) so judges can install, run, and verify without guessing

## Judging criteria


| Criterion               | Weight | Description                                                                                                                            |
| ----------------------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------- |
| **Expressiveness**      | 25%    | How much of a real contract can your system capture? Obligations, conditions, deadlines, penalties, definitions, cross-references?     |
| **Executability**       | 25%    | Does the computer actually *run* the representation? Conditions, values, state, enforcement, or is it only data?                       |
| **Round-trip fidelity** | 25%    | Does English from the executable preserve meaning and completeness? Is executable → English deterministic and LLM-free, as required?   |
| **Generality**          | 15%    | Does it work across contract types, including material not identical to the published samples? (Judges evaluate each submission on the same set of held-out Markdown contracts.) |
| **Creativity**          | 10%    | Novel approaches, clean design, ambitious scope                                                                                        |


## Submission requirements

- GitHub repo with source
- Working demo (live, recorded, or notebook) showing the full pipeline on at least one sample contract
- **Base** demo documented with **fewer than 10 numbered steps** from clean environment to verified output (install, commands, what to check)
- Short writeup (repo or slides) on approach, design choices, and limitations

## Optional stretch goals

Not required. They can help **Creativity** and **Expressiveness** if you have time:

- **Traceability / provenance:** machine-checkable links from source clauses to IR nodes to regenerated English
- **Multi-party reasoning:** distinct roles (lender/borrower, landlord/tenant) with obligations keyed to party
- **Amendments and versioning:** layer changes on a base agreement and run logic against effective text
- **Counterfactuals:** "What if payment were on this date?" or other comparative scenarios from one executable model
- **Definitions and cross-references:** resolve defined terms and internal references before execution
- **Testing or properties:** example-based tests over your IR, or stated invariants (e.g. fees never negative) where applicable

## Rules

- All code must be written during the hackathon
- You may use any programming language, framework, or AI model **except** on **executable → English**, which must be deterministic and **must not use LLMs** (see Part 2). **Expect to use an LLM** (or equivalent) to **generate scenario/sample data** so runs work on held-out contracts (see **Execution data**)
- Pre-existing open-source libraries and tools are allowed (with attribution)

---

## Design questions worth deciding early

You do not have to solve everything but teams that pick a direction for these tend to move faster:

- **Intermediate representation (IR).** Is it a tree, a graph, rows in a table, bytecode, or something else? Can you version it as you iterate?
- **Scenario data.** What format holds the facts you need to run the contract (JSON, YAML, structs, DB rows)? Where does an **LLM** turn contract text (or your IR) into that data for held-out runs? How does a judge reproduce or inspect a run?
- **Time.** How do you represent "within 10 business days of receipt" versus calendar days? What is your clock for simulations?
- **Parties.** Are obligations always attached to named roles, or do you infer from text on the fly?
- **Partial coverage.** If you only formalize part of a contract, how do you report that in the regenerated English (omit, stub, or mark as unmodeled)?
- **Deterministic decompiler.** Where does the template or grammar live, and how do you prove the English step never calls an LLM?

## Concrete example (illustrative)

Suppose you focus on the credit card agreement. A credible demo might: ingest the Markdown, extract the APR and fee rules you chose to model, represent them in your IR, use an **LLM** to produce scenario rows or a timeline (on-time payment, late payment, different balance tiers if the text supports it), run the executor on that data, print numeric results, then emit regenerated English that restates those rules in plain language. The point is visible numbers and logic, not a perfect model of the full agreement.

## Pitfalls that show up a lot

- **IR without a runner.** If nothing evaluates, you have a schema, not executability.
- **Contract text only.** If the demo prints results but never shows the **input facts** that drove them, execution looks like a black box.
- **Hand fixtures only.** If scenario data is always typed by humans and never LLM-generated from the contract, you may fail on **held-out** inputs where no fixtures exist.
- **LLM in the decompiler by accident.** Wrapping "turn this JSON into prose" with an API call fails the hard rule even if the rest of the project is solid.
- **Nondeterminism.** Floating-point surprises, unordered iteration over hash maps, timestamps in output. If judges diff twice and get different English, that is a problem.
- **Demo drift.** The video shows one path; the README describes another. Keep them aligned.
- **Only happy paths.** Showing one scenario is fine; saying what breaks or is out of scope is better than silent failure.

## FAQ

**Can we preprocess Markdown (split sections, normalize headings) before the main pipeline?** Yes, if you document it. Judges need to follow from raw or preprocessed input consistently with what you describe.

**Are we allowed to hand-annotate samples for our own testing?** For your repo and experiments, yes. Your submission should still demonstrate behavior on the shared inputs organizers care about; check any event-specific rules if published separately.

**Does "deterministic" mean byte-identical English across machines?** Prefer yes for the same IR. If minor whitespace differs, say so and show what you normalize. Do not hide randomness behind "usually the same."

**Why ban LLMs only on executable → English?** So the round-trip has a verifiable, repeatable artifact. Parsing messy language with help from a model is a different problem from proving the compiled English is a function of your IR.

**Why require an LLM for scenario/sample data?** Held-out Markdown does not ship with fixtures. Your pipeline needs a step that uses an **LLM** to propose structured facts and events so the executor can run on those files. That is separate from the executable → English ban.

**Is Solidity required?** No. Use what fits your demo.

## What the base demo steps should include

Aim for steps that a judge can run in order without opening your codebase to guess intent:

1. Environment (language version, OS assumptions if any).
2. How to install dependencies.
3. Exact command(s) to run the pipeline on a named sample file (and, if applicable, the scenario or fact data file or flags you use to drive execution).
4. Where output appears (stdout, file path).
5. How to confirm execution happened (numbers, state dump, log line you define), including how to see or edit the **input data** that produced those results.
6. How to run the English generation step alone, if split from parsing.
7. How to verify determinism (e.g. run twice, diff).
8. Optional: where the writeup or recorded demo lives.

You do not need ten steps for the sake of ten; you need **under ten** clear steps with no missing rungs.

## Glossary (quick)

- **IR:** Your internal representation of contract logic (whatever structure you choose).
- **Executable:** The IR plus whatever runs it (interpreter, VM, evaluator).
- **Round-trip:** Markdown in → executable → English out, with substance preserved.
- **Held-out:** The same set of Markdown contract files judges use to evaluate every submission; not shipped in this public repo.

## Contact

Questions about this track? Reach out to Ayush at [ayush@sharpe.com](mailto:ayush@sharpe.com).