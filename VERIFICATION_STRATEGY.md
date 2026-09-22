# Verification Strategy and Results

This document maps each DUT's behavior/requirements to the verification
mechanisms that check them, states plainly what each mechanism proves
and does **not** prove, and records the actual measured results from
the regression (not aspirational numbers). It deliberately keeps test
pass rate, functional coverage, mutation score, formal proof status,
and lint findings **separate** -- combining them into one project score
would hide exactly the information a reviewer needs (e.g. "100%
mutation score" means something different depending on which mechanism
achieved it, and collapsing that away is misleading).

No claim in this document should be read as "fully verified" or
"formally verified end to end". Every mechanism here has a specific,
bounded scope, stated explicitly.

## What each mechanism proves, and does not prove

| Mechanism | What it actually establishes | What it does NOT establish |
|---|---|---|
| Directed simulation tests | The DUT behaves correctly for the *specific* stimulus sequences exercised | Anything about stimulus not exercised |
| Constrained-random simulation | The DUT behaves correctly across a *guaranteed-representative, randomized* sample of stimulus (every required scenario/coverage cell hit deterministically; specific values/ordering randomized) | Exhaustive coverage of the full input space -- it is still sampling, just a better-distributed sample than fixed directed vectors |
| Functional coverage | Which defined structural/behavioral categories were exercised at least once | Correctness -- a covered bin says stimulus reached that category, not that the DUT responded correctly there (that's the scoreboard/checkers' job); also says nothing about categories not defined as bins |
| Scoreboard / reference model | Output data values match an independently-computed expected value, for every transaction actually observed | Anything about untested internal states; a scoreboard bug could in principle mask a DUT bug (mitigated, not eliminated, by mutation testing) |
| Protocol checker | Data-independent structural/timing invariants hold on every cycle observed during the run it's attached to | Data correctness (deliberately never knows the expected value) |
| Latency checker (APB) | The exact cycle count of every operation *actually observed* during a run matches `OP_LATENCY` | Behavior of operations not exercised in that run (that's what P3, formal, covers exhaustively) |
| Mutation testing | The testbench actually detects each specific, hand-selected injected defect, attributed to the mechanism(s) that caught it | Detection of defect classes no mutant represents; a mutation score is only as good as the mutant set's realism/diversity (see the per-DUT review in each `VERIFICATION_PLAN.md`) |
| Formal properties | The stated property holds for *every* reachable input at *every* cycle (k-induction: for all time; BMC: up to the checked depth, or exhaustively if the property has no dependence on history -- see below) | Anything not stated as one of the 3 properties; formal here covers 3 narrow, deliberately chosen claims, not the DUT's full functional correctness |
| Lint | Style/structural issues a static tool can detect (missing defaults, untyped parameters, POSIX formatting) | Functional correctness at all -- lint findings here are cosmetic and explicitly not fixed where fixing them would conflict with other constraints (documented per-DUT) |

## UART TX (`phase1_uart/`)

| Requirement | Directed | Random | Coverage | Scoreboard | Protocol checker | Mutation | Formal |
|---|---|---|---|---|---|---|---|
| Correct 8N1 framing/data value, LSB-first | `test_uart_tx_basic` | `test_uart_tx_random_sweep` | `tx_data_class` | ✓ (data-value) | -- | mutant1/2/5/6/9 target this class | not attempted (see below) |
| Every bit period constant for exactly `CLKS_PER_BIT` cycles | `test_uart_tx_timing` | via monitor on every random transaction | -- | ✓ (segment constancy) | ✓ (start/stop/segment timing) | mutant3/6/9 | not attempted |
| `tx_busy` asserted for the full frame, deasserts correctly | all tests (via `busy_ok`) | ✓ | -- | ✓ | -- | mutant4 (also caught by driver's bounded timeout) | not attempted |
| Structurally distinct byte patterns (zero/all-one/alternating/walking-one/other) | `test_uart_tx_coverage_sweep` | ✓ (guaranteed) | `tx_data_class` x `tx_mode` (10 cells) | ✓ | -- | -- | -- |
| Back-to-back framing, including 3+-frame chains | -- | `back_to_back_chain_length` (guaranteed 2 and 3+) | ✓ | ✓ | -- | -- | -- |
| Idle-gap timing variation | -- | `idle_gap_class` (guaranteed all 3) | ✓ | ✓ | -- | -- | -- |
| Reset mid-frame recovers safely | `test_uart_tx_reset_mid_frame` | -- | `reset_mid_transmission` | ✓ | -- | mutant7 (only via `coverage_directed` mechanism -- `test_uart_tx` alone never resets after leaving IDLE) | -- |
| `tx_data` changing mid-frame doesn't corrupt the transmitted byte | `test_uart_tx_data_latched` | -- | -- | ✓ | -- | mutant8 | -- |

UART has **no formal properties** (Phase 7 deliberately scoped formal to
APB only -- UART's comparable defect classes are already exhaustively
represented in its 9-mutant, 3-mechanism mutation suite with no
unresolved gap, so formal there would add lower-differentiated value
than the two properties chosen for APB; see the Phase 7 design
reasoning in `phase5_apb/VERIFICATION_PLAN.md`'s introduction).

## APB4-Lite register block (`phase5_apb/`)

| Requirement | Directed | Random | Coverage | Scoreboard | Protocol checker | Latency checker | Mutation | Formal |
|---|---|---|---|---|---|---|---|---|
| Register R/W semantics (CTRL/STATUS/DATA/INTCLR) | `test_apb_data_rw`, `test_apb_reserved_bits_masked` | ✓ | `reg_class` x `direction` (10 cells) | ✓ | -- | -- | mutant2/6/7 | -- |
| PSLVERR correctness (illegal write/read) | `test_apb_illegal_accesses` | ✓ (guaranteed, all 4 illegal classes) | (same cross, illegal cells) | ✓ | -- | -- | mutant1/8 | **P1 -- all 256 addresses x both directions** |
| START accepted only with prior ENABLE, ignored while disabled/busy | `test_apb_operation_accepted`, `test_apb_start_same_write_is_noop`, `test_apb_start_while_disabled_is_noop`, `test_apb_start_while_busy_is_ignored` | ✓ (guaranteed, all 3 `start_control` outcomes) | `start_control` (3 bins) | ✓ | -- | -- | mutant3 (see `LESSONS_LEARNED.md` -- initially survived every mechanism due to a test-timing gap, not a real gap) | **P2 -- exhaustive over all interfering-write timings, unbounded** |
| Operation completes in exactly `OP_LATENCY` cycles | (implicit in all operation tests) | ✓ | -- | -- (deliberately not checked here -- see below) | -- | ✓ (every operation actually run) | mutant4/5 | **P3 -- exhaustive over all reachable states, unbounded** |
| INTCLR write-1-to-clear semantics | `test_apb_intclr` | ✓ (guaranteed both outcomes) | `intclr_effect` (2 bins) | ✓ | -- | -- | mutant6 | -- |
| APB SETUP->ACCESS bus protocol (any legal master sequencing) | all tests, implicitly | ✓ | -- | -- | ✓ (every cycle of every test) | -- | mutant9 | not attempted (the checker already covers this class in every simulation run; formal would be proving the same claim redundantly) |
| Reset mid-operation recovers safely | `test_apb_reset_mid_operation` | -- | -- | ✓ | -- | ✓ (aborted ops excluded, not miscounted) | -- | (reset handling is an assumption inside P2/P3, not a separate property) |

**Why the scoreboard deliberately does not check `OP_LATENCY` exactness:**
the reference model is "software-realistic" -- it learns an operation
finished only by observing `BUSY=0` via polling, the same way real
firmware would. A transaction-level model that only checks "eventually
finished" cannot, by construction, distinguish a correct latency from an
off-by-one defect landing between two polls. That's precisely why
`ApbLatencyChecker` (cycle-accurate, independent) and formal property P3
(exhaustive over all reachable states) exist as separate mechanisms
instead of folding this into the scoreboard.

## Formal proof status -- exact and unhedged

| Property | Proof type | What this means |
|---|---|---|
| P1 (PSLVERR correctness) | **BMC, depth 5** | The property was checked at every step up to depth 5. This is *not* an unbounded proof in the general sense -- but the property is purely combinational (depends only on the current-cycle inputs, never on any register), so its truth at any one step does not depend on history. Proving it at every checked step is therefore a complete proof over the entire interface input space (all 256 `PADDR` values x both directions x every `PSEL`/`PENABLE` combination), even though the proof engine used is BMC, not induction. This is a property of *this specific claim*, not a general property of BMC results -- do not generalize it to "BMC proves things for all time." |
| P2 (no restart while busy) | **k-induction, converged -- unbounded** | Proven true for all time, for any reachable state and any sequence of interfering CTRL writes (excluding DATA-address writes while busy, an explicit, documented, narrow scoping assumption -- see below). |
| P3 (BUSY bounded by `OP_LATENCY`) | **k-induction, converged -- unbounded** | Proven true for all time, for any reachable state. |

**Assumptions used by the proofs (all explicit, none hidden):**
- All three: the trace is assumed to begin with a genuine reset
  (`initial assume (!PRESETn)`). Without this, BMC is free to start from
  an arbitrary, physically-meaningless register state -- found by direct
  testing (a counterexample trace that simply never reset at all), not
  assumed in advance.
- P2 only: DATA-address writes are assumed not to occur while an
  operation is busy. This is a narrow, deliberate scoping decision, not
  a weakening to force a pass -- a DATA write while busy is legal at the
  bus level and legitimately changes what value the eventual
  auto-increment operates on (already modeled in
  `apb_env/reference_model.py`); excluding it keeps P2 focused on what
  it is actually about (the CTRL/START retrigger guard) rather than
  conflating two unrelated, separately-understood behaviors. CTRL
  writes -- every ENABLE/START combination, including illegal ones --
  remain completely unconstrained throughout.

**Toolchain / SystemVerilog limitations, verified not assumed:**
- No SVA. Every property is a plain procedural `assert`/`assume` inside
  an `always @(posedge PCLK)` block. `property`/`sequence` SVA blocks
  were never tested against this toolchain's Yosys frontend and are not
  claimed to work.
- Hierarchical cross-module references (`dut.some_internal_reg`) are not
  reliably modeled by this toolchain -- confirmed with a trivial
  tautology (`busy_o == dut.busy_reg`, true by definition) that produced
  a false counterexample. All formal harnesses observe the DUT only
  through real output ports (`busy_o`, `data_o`) as a result.
- Formal covers exactly 3 properties on 1 DUT. It is not a substitute for
  the scoreboard, protocol checker, coverage, or mutation testing, all of
  which continue running independently and cover everything else.

## Measured results (this run)

Produced by `python run_regression.py` at commit `1da43af`, full output
in `regression_results/report.json`/`report.md` (gitignored --
regenerated by re-running the command). These are the actual numbers
from that run, not representative/rounded figures.

**Overall regression status: PASS.** ("Overall" here means every test
suite passed, mutation testing produced no `UNKNOWN` verdicts, and every
formal property passed -- see "Pass/fail semantics" in `README.md`. It
is a build-health signal, not a combined quality score.)

### Test pass rate

| Suite | Result | Seed |
|---|---|---|
| `test0_sanity` | 1/1 | -- |
| `uart_directed` | 2/2 | -- |
| `uart_coverage_directed` | 4/4 | -- |
| `uart_random` | 2/2 | 284863992 |
| `uart_checker_only` | 1/1 | -- |
| `apb_directed` | 10/10 | -- |
| `apb_random` | 2/2 | 1112575254 |
| `apb_checker_only` | 1/1 | -- |
| `apb_latency_only` | 1/1 | -- |

24/24 tests passed. Random suite seeds are recorded here as a concrete
example of the reproducibility mechanism -- re-running
`make MODULE=test_uart_tx_random COCOTB_RANDOM_SEED=284863992` (or the
APB equivalent) reproduces that exact run's stimulus.

### Functional coverage

`top` (the aggregate) is **not the meaningful number** for the two UART
modules -- see the "Is the Phase 2 100% coverage number still
meaningful?" discussion in `phase1_uart/VERIFICATION_PLAN.md`: each
module only samples the CoverPoints it owns, and `cocotb-coverage`'s
`coverage_db` is a process-wide singleton, so a module's `top` includes
points a *different* module is responsible for closing.

- `uart_coverage_directed`: its 4 owned points/cross (`tx_data_class`,
  `tx_mode`, their cross, `reset_mid_transmission`) all **100.0%**.
- `uart_random`: its 2 owned points (`idle_gap_class`,
  `back_to_back_chain_length`) both **100.0%**.
- `apb_random`: all 5 points/cross **100.0%** (APB has a single
  coverage module, so its `top` figure of 100.0% is meaningful as-is).

### Mutation score

| DUT | Combined | Per mechanism |
|---|---|---|
| UART | **9/9 (100.0%)** | `coverage_directed` 9/9 (100%), `scoreboard` 7/9 (77.8%), `protocol_checker` 6/9 (66.7%) |
| APB | **9/9 (100.0%)** | `scoreboard` 9/9 (100%), `latency_checker` 2/9 (22.2%), `protocol_checker` 1/9 (11.1%) |

The combined score is 100% for both, but the per-mechanism spread is the
actually informative number: no single mechanism catches everything on
its own (UART's `scoreboard` misses 2/9; APB's narrower mechanisms miss
most, by design -- they're built to catch specific defect classes, not
everything). Full per-mutant, per-defect-category tables are in
`regression_results/report.md` after running the regression, and in
each DUT's `VERIFICATION_PLAN.md`.

### Formal proof status

| Property | Status | Proof type |
|---|---|---|
| P1 (PSLVERR correctness) | PASS | bounded (BMC, depth 5) -- complete for this claim, see above |
| P2 (no restart while busy) | PASS | **unbounded (k-induction)** |
| P3 (BUSY bounded) | PASS | **unbounded (k-induction)** |

### Lint

| DUT | File | Findings |
|---|---|---|
| UART | `uart_tx.v` | 4 (2 untyped parameters, 1 missing `case` default, 1 missing trailing newline) |
| APB | `apb_regblock.v` | 4 (4 untyped parameters -- 2 of 6 original findings were fixed in Phase 5 before any mutants existed) |

None of these are functional bugs; none are fixed, for reasons specific
to each (documented in the respective `VERIFICATION_PLAN.md`) -- mainly
that fixing them now would require regenerating every mutation-suite
mutant to preserve the "exactly one injected difference from golden"
property those files depend on.

## Equivalent mutants deliberately rejected (not added, to avoid inflating the count)

- **UART**: removing `bit_idx<=0`/`busy_reg<=0` from the `rst` branch.
  Traced through the RTL and confirmed both are unconditionally
  re-assigned by the `IDLE` state's own case branch on the very next
  reachable cycle, making this a true equivalent mutant -- no test could
  ever distinguish it from golden RTL.
- **APB**: `PREADY` tied to `PSEL` alone instead of a constant `1`.
  `PSEL` is already `1` throughout every ACCESS phase by construction
  (the master holds it asserted through SETUP and ACCESS), so this is
  indistinguishable from `PREADY=1` in every cycle that actually
  matters -- also a true equivalent mutant.

Neither was added to its mutation suite. See `LESSONS_LEARNED.md` for
the full reasoning and for mutants that *were* added only after a
genuine defect-class review found a real gap.
