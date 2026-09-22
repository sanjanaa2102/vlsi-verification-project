# Architecture

This document explains how the project is put together: the overall
repository structure, each DUT's verification environment, the generic
mutation engine, the unified regression framework, the formal
verification layer, and how these pieces interact. For *why* each
design decision was made (including the ones that turned out to be
wrong on the first attempt), see the per-DUT `VERIFICATION_PLAN.md`
files and `LESSONS_LEARNED.md`. For a mapping of DUT requirements to
verification mechanisms and the actual measured results, see
`VERIFICATION_STRATEGY.md`.

## Repository layout

```
test0/            minimal cocotb sanity test (AND gate) -- toolchain smoke test
phase1_uart/       UART TX DUT + its verification environment (uart_env/)
phase2_llm/        the same UART TX DUT, verified by an LLM-generated testbench
                    instead -- a separate research track, out of scope for
                    Phases 6-8's regression/CI/documentation work
phase5_apb/        APB4-Lite register block DUT + its verification environment
                    (apb_env/) + formal properties (formal/)
mutation/          generic, DUT-agnostic mutation-testing engine
regression/        unified regression orchestrator (test/coverage/lint/
                    mutation/formal orchestration, report generation)
run_regression.py  the one-command entry point built on regression/
formal_tools/       gitignored -- SymbiYosys, fetched automatically on first
                    formal run (see phase5_apb/formal/ below)
regression_results/ gitignored -- generated reports and failure artifacts
.github/workflows/  CI (GitHub Actions)
```

Two DUTs share almost nothing in code -- no common base class, no
shared driver/monitor implementation -- by design. UART's async-frame
protocol and APB's blocking request/response protocol are different
enough that forcing a shared class hierarchy would have been the kind
of premature abstraction this project has otherwise avoided. What *is*
shared is the **pattern** (driver / monitor / reference model /
scoreboard / protocol checker / coverage / constrained sequences) and,
concretely, the mutation engine and the regression framework, both of
which are genuinely DUT-agnostic.

## UART verification environment (`phase1_uart/`)

DUT: a parameterized UART transmitter (`uart_tx.v`, 8N1 framing,
`CLKS_PER_BIT` configurable).

```
uart_env/
  driver.py          stimulus only -- send_byte(), reset(), no checking
  monitor.py          passively decodes frames from tx_serial/tx_busy,
                       independent of what the driver intended to send
  reference_model.py  pure Python, no DUT/cocotb dependency
  scoreboard.py        the only place a data-value pass/fail judgement
                       happens, against the reference model
  checker.py           protocol/timing invariants (start/stop bit,
                       segment timing, frame duration) -- independent of
                       the scoreboard, never told what byte was sent
  coverage.py           functional coverage (cocotb-coverage)
  sequences.py          constrained-random stimulus generation
  harness.py            shared setup/teardown, wires everything together
```

Test files (`test_uart_tx*.py`) are thin: they sequence driver calls and
`scoreboard.expect()` calls, and let the shared harness/checker do the
rest. `test_uart_tx.py` is deliberately the one `run_mutants.py` (the
original Phase 3 mutation script, preserved unchanged) targets, so its
behavior has stayed stable since Phase 2.

Driver is **non-blocking**: `send_byte()` issues the start pulse and
returns immediately; the monitor observes completion independently.
This is a direct consequence of UART being an open-ended async frame,
not a request/response protocol.

## APB verification environment (`phase5_apb/`)

DUT: a small but functionally real APB4-Lite register block
(`apb_regblock.v`) -- CTRL/STATUS/DATA/INTCLR registers, a genuine
multi-cycle operation with a configurable `OP_LATENCY`, and
register-map-legality error responses (`PSLVERR`). Two
verification-only observability ports (`busy_o`, `data_o`) exist purely
for white-box checking/formal reasoning -- neither is part of the APB
interface and no test needs them to be exact-model the DUT's I/O.

```
apb_env/
  driver.py             stimulus only -- write()/read(), blocking
  monitor.py             reconstructs each completed transaction from bus
                         observation alone
  reference_model.py     pure Python state machine (ENABLE/DATA/BUSY/DONE)
  scoreboard.py            data-value AND register-map-legality (PSLVERR)
                         comparison against the reference model
  checker.py               pure APB bus-interface invariants (SETUP->ACCESS
                         sequencing, PENABLE/PSEL relationship, signal
                         stability, PREADY during ACCESS) -- deliberately
                         does NOT know about the address map
  latency_checker.py       cycle-accurate check that an operation takes
                         exactly OP_LATENCY cycles, via busy_o -- independent
                         of the scoreboard's software-polling-based model
  coverage.py               functional coverage
  sequences.py              constrained-random value-generation primitives
  harness.py                shared setup/teardown
formal/
  apb_regblock_p1_pslverr.sv/.sby       PSLVERR correctness
  apb_regblock_p2_no_restart.sv/.sby     no restart while busy
  apb_regblock_p3_busy_bounded.sv/.sby   BUSY bounded by OP_LATENCY
  apb_regblock_fixture_fault_p2p3.v      a dedicated faulty-RTL fixture used
                                        only to demonstrate P2/P3 actually
                                        catch a bug (NOT one of the 9
                                        mutation-suite mutants)
```

Driver is **blocking**: `write()`/`read()` return once the transaction
completes, matching APB's SETUP->ACCESS request/response shape.

Register-map legality (whether a given `PADDR`/direction combination is
legal, i.e. `PSLVERR` correctness) lives in the **scoreboard**, not the
protocol checker -- it is a fact about this specific device's address
map, not a rule any APB4 slave must obey, so mixing it into the
protocol checker would misrepresent an implementation detail as a
protocol requirement.

## Generic mutation engine (`mutation/`)

`mutation/framework.py` + `mutation/report.py`: given a DUT directory
and a manifest of `Mutant` (name, RTL file, defect category,
description) and `Mechanism` (name, cocotb test module) objects, it
runs `make clean && make VERILOG_SOURCES=<mutant> MODULE=<mechanism>`
for every mutant x mechanism pair, classifies CAUGHT/SURVIVED from
cocotb's own `FAIL=<n>` summary line, and produces a report
(total/caught/survived/score, per-mechanism, per-defect-category,
per-mutant, JSON export). It has **zero UART- or APB-specific code** --
`phase1_uart/mutation_suite.py` and `phase5_apb/mutation_suite.py` are
both just manifests built on this same, unmodified engine. A future DUT
reuses it the same way: write a manifest, not a runner.

`phase1_uart/run_mutants.py` and `run_mutants_checker.py` are older,
narrower, single-mechanism scripts from Phase 3, preserved unchanged
alongside the generalized engine -- both still work and still produce
identical results, demonstrating the newer engine didn't silently
change anything about the underlying mutants or RTL.

## Unified regression framework (`regression/`, `run_regression.py`)

```
regression/
  runner.py    drives make for each test suite, extracts coverage YAML,
               runs lint, runs mutation_suite.py -- all via subprocess,
               treating each DUT directory as a black box
  formal.py     drives SymbiYosys for each formal property, fetches sby
               automatically on first use, extracts counterexample
               artifacts on failure
  parsers.py    reads cocotb's results.xml (JUnit-style XML), exported
               coverage*.yml, and verible-verilog-lint's structured
               output -- machine-readable sources, not console-text
               scraping
  report.py     builds one unified result object, renders it as
               regression_results/report.json (machine-readable) and
               report.md (human-readable)
```

`run_regression.py` is the thin CLI entry point: it sequences 9 test
suites (`test0` sanity, UART directed/coverage-directed/random/
checker-only, APB directed/random/checker-only/latency-only), lint on
both RTL files, both DUTs' full mutation suites, and the 3 formal
properties, in that fixed order. Coverage is extracted **immediately
after** the suite that produces it (not in a separate pass at the end)
because every suite's `make clean` wipes the DUT's shared `sim_build/`
directory -- see `LESSONS_LEARNED.md` for why this was a real bug, not
a design choice made correctly the first time.

Every random suite's seed is generated by the orchestrator *before* the
suite runs (so it's recorded even on failure), passed through as
`COCOTB_RANDOM_SEED=<seed>`, and reported. Failure diagnostics
(simulator log, and for single-`make` suites, a re-run with `WAVES=1`
to capture a waveform; for formal properties, SymbiYosys's own
counterexample `.vcd`/testbench-replay/witness files) are only
generated for suites that actually fail -- nothing extra for passing
suites.

Neither report collapses to a single number: test pass/fail, coverage
(per CoverPoint), mutation (per mechanism, per defect category, per
mutant), formal (per property, with proof type), and lint (per finding)
are each their own section. See `VERIFICATION_STRATEGY.md` for why
these are deliberately never combined into one score.

## Formal verification layer (`phase5_apb/formal/`)

Three properties on `apb_regblock` only (see `VERIFICATION_STRATEGY.md`
and `phase5_apb/VERIFICATION_PLAN.md` for what each proves and why).
Toolchain: `yowasp-yosys` + `yowasp-yosys-smtbmc` (Yosys compiled to
WebAssembly, pip-installable) + `z3-solver` (pip-installable Z3) driven
by real SymbiYosys (`sby`, fetched at a pinned git tag on first use,
since it has no PyPI package). All free, no sudo/apt, no billing.
Properties are plain procedural `assert`/`assume` statements in
`always @(posedge PCLK)` blocks -- not SVA `property`/`sequence` blocks,
which were never tested against this toolchain and are not claimed.

Entirely independent of the simulation-side scoreboard/checkers: no
Python code, no cocotb, nothing shared. The only place formal RTL and
simulation RTL connect is that both read the same `apb_regblock.v` --
formal harnesses instantiate it unmodified as a submodule, exactly like
a testbench would.

## How the pieces interact

```
                     run_regression.py
                            |
              +-------------+-------------+-------------------+
              |             |             |                   |
        regression/runner.py    regression/formal.py    regression/report.py
              |             |             |
     +--------+--------+    |    +--------+--------+
     |                 |    |    |                 |
 phase1_uart/      phase5_apb/   phase5_apb/    mutation/
 (make, uart_env)  (make,        formal/        (framework.py,
                    apb_env)     (sby, yosys,    used by both DUTs'
                                  z3)            mutation_suite.py)
```

`regression/runner.py` never imports from `uart_env/` or `apb_env/` --
it only shells out to `make` and reads the artifacts those commands
already produce. This means the orchestrator cannot accidentally change
simulation behavior, and each DUT's environment can be understood,
tested, and debugged completely independently of the regression
framework that wraps it.
