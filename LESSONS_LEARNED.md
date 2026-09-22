# Engineering Lessons

Real bugs, tool limitations, and design mistakes found during
implementation, and how each was actually diagnosed -- not smoothed
over. Every one of these was found by instrumenting the simulator or
formal tool and looking at real output, not by reasoning it out in
advance and assuming the reasoning was correct. That discipline (verify
empirically, don't trust a derivation you haven't checked) is the
throughline connecting all of them.

## 1. Coverage artifact lifecycle issue

**Symptom:** the first version of `run_regression.py` produced an empty
"Functional Coverage" section in its report, even though the individual
`make MODULE=...` commands, run by hand, clearly exported real coverage
YAML files.

**Cause:** every suite's `make clean` deletes the DUT's `sim_build/`
directory. The orchestrator originally ran all 9 suites first, then
tried to read every coverage YAML in one pass at the end -- by which
point, each DUT's `sim_build/` only contained whatever the *last* suite
for that DUT happened to produce (and the last APB/UART suites run
don't export coverage at all).

**Fix:** extract each suite's coverage immediately after that suite
runs, before the next suite's `make clean` can delete it. See
`run_regression.py`'s comment at the call sites.

## 2. Mutation framework working-directory issue

**Symptom:** `mutation/framework.py` worked correctly every time it had
ever been run (Phases 4 and 5) -- until Phase 6's orchestrator called it
from the repository root instead of from inside the DUT directory, at
which point every single mutant run failed with `make: *** No rule to
make target '.../dut.v'`.

**Cause:** the project's Makefiles reference `$(PWD)`, which GNU Make
resolves from the *inherited* `PWD` environment variable when the
Makefile doesn't define it itself -- not from `subprocess.run`'s `cwd=`
argument. Every previous invocation of `mutation/framework.py`
(including by hand and by `mutation_suite.py`) happened to be launched
from a shell already `cd`'d into the DUT directory, so the inherited
`PWD` always happened to already match. Phase 6's orchestrator, running
from the repo root, was the first caller where that coincidence didn't
hold, and the bug -- present since Phase 4 -- became visible.

**Fix:** explicitly pass `env=dict(os.environ, PWD=dut_dir)` to every
`subprocess.run` call in `mutation/framework.py` and `regression/runner.py`.
Re-verified both DUTs' mutation results were unchanged after the fix
(same 9/9, same per-mechanism breakdown) -- the fix corrected a
robustness gap, not a functional result.

## 3. Bounded wait-loop issue

**Symptom (UART, Phase 4):** `run_mutants.py` hung indefinitely against
`mutant4_busy_stuck_high`, instead of failing.

**Cause:** `UartTxDriver.wait_idle()` polled `tx_busy` in an unbounded
`while` loop. A mutant that makes `tx_busy` stuck high causes that loop
to spin forever -- a hang is a worse regression-CI outcome than a clean
failure, since it can block or time out an entire pipeline rather than
reporting one failed test.

**Fix:** bounded the loop (`max_cycles`, raising a clear
`AssertionError` past the bound).

**Recurrence (APB, Phase 5):** the same class of bug reappeared in
`ApbDriver.wait_busy_clear()` and had to be independently bounded there
too -- finding it once in UART did not automatically prevent it in the
structurally different APB driver; each wait loop needed to be checked
on its own.

## 4. Reset-state handling

Multiple, separate issues, all in the same family:

- **UART (Phase 4):** `test_uart_tx_coverage`'s reset-mid-frame test hung
  against `mutant7_incomplete_reset`, for the *same* unbounded-loop
  reason as #3 above -- `send_byte()`'s "wait for `tx_busy` to rise"
  loop had no bound either, and a broken reset meant `tx_busy` never
  rose again after the interrupted frame.
- **UART/APB checkers:** both `UartTxProtocolChecker` and
  `ApbLatencyChecker` originally didn't account for a reset occurring
  mid-measurement, which would have flagged a deliberately-tested
  reset-abort scenario as a timing violation. Fixed by checking
  `PRESETn`/`rst` inside the measurement loop and excluding aborted
  operations from both the count and violation checking, rather than
  scoring them as pass or fail.
- **Formal (Phase 7):** BMC is free to choose an initial state where
  reset is *never* asserted at all, leaving every register at an
  arbitrary, physically-meaningless starting value. Found via a
  counterexample trace that, on inspection, literally never reset.
  Fixed with `initial assume (!PRESETn)` in every formal harness.
- **APB RTL itself (Phase 5):** the first draft of `apb_regblock.v`
  declared registers without Verilog initial values (unlike UART's
  `reg busy_reg = 1'b0;` style), so reads at true simulation time 0 (before
  any clock edge) returned `X` and crashed `int()` in the Python
  checkers. Fixed by giving every register an explicit initial value,
  *and*, defensively, by not reading any DUT signal synchronously before
  the first `RisingEdge` in checker code regardless.

The pattern across all four: reset is not a detail to handle once and
forget -- every new mechanism that observes DUT state (a checker, a
formal harness, a driver synchronization loop) has to independently
account for what happens during and immediately after reset.

## 5. Formal hierarchical-reference limitation

**Symptom:** a P2/P3 harness draft that read `dut.busy_reg`/`dut.data_reg`
via hierarchical reference produced a formal counterexample against
*golden* RTL -- RTL that had already passed extensive directed, random,
and mutation testing.

**Diagnosis, not assumption:** rather than trust that golden RTL must be
wrong, the exact counterexample input sequence was replayed through
Icarus (a simulator this project fully trusts), which showed correct
behavior throughout with no violation. That ruled out a real DUT bug.
The root cause was confirmed with a minimal, deliberately trivial
sanity check: `assert (busy_o == dut.busy_reg)` -- true by definition,
since `apb_regblock.v` literally assigns `busy_o = busy_reg` -- which
*also* produced a false counterexample under this toolchain's formal
flow. That is a definitive proof the toolchain does not reliably model
hierarchical cross-module references, independent of any property
logic.

**Fix:** added `data_o`, a verification-only observability port
mirroring the already-established `busy_o` precedent from Phase 5, to
`apb_regblock.v`. All formal harnesses observe the DUT only through real
output ports now. This was a deliberate, narrow, well-precedented RTL
addition to work around a confirmed tool limitation -- not a change made
to force a property to pass (no functional behavior changed; confirmed
via diff and via unchanged mutation results after the change).

## 6. Over-constrained (actually: over-strong) first version of P2

**Symptom:** an early version of the "no restart while busy" property
(before the `data_o` fix even, and again after it) produced a
counterexample where the DUT's behavior was actually correct.

**Diagnosis:** the counterexample showed a *legal* CTRL write sequence
followed by a *legal* write directly to the DATA register while the
operation was still in flight -- which `apb_env/reference_model.py` had
already documented as legal, intentional behavior since Phase 5 (a
DATA write while busy legitimately changes what value the eventual
auto-increment operates on). The property as originally stated
("DATA at completion == DATA at acceptance + 1", unconditionally) was
simply too strong -- it conflated an unrelated, already-understood
legal behavior with the specific defect class (a busy-guard bypass) it
was meant to catch.

**Fix:** added one narrow, explicit, documented scoping assumption
(DATA-address writes are excluded specifically while busy) so the
property stays focused on what it's actually about. This is different
in kind from "weakening a property to force a pass": it is scoping a
claim to be about one specific mechanism (the retrigger guard) instead
of silently asserting something broader and wrong. CTRL writes --
every ENABLE/START combination, including illegal ones -- remain
completely unconstrained.

## 7. Equivalent mutants deliberately rejected

Two candidate mutants were designed, reviewed, and **not added** to
their mutation suites, specifically to avoid inflating the mutant count
with something no mechanism could ever catch:

- **UART:** removing `bit_idx<=0`/`busy_reg<=0` from the reset branch.
  Both are unconditionally re-assigned by the `IDLE` state's own case
  branch on the very next reachable cycle -- traced through the RTL and
  confirmed there is no reachable scenario where this difference from
  golden RTL is externally observable.
- **APB:** `PREADY` tied to `PSEL` alone instead of the constant `1`.
  `PSEL` is already `1` throughout every ACCESS phase by construction
  (the master holds it asserted through SETUP and ACCESS), so the two
  expressions are indistinguishable in every cycle that matters.

Both are documented in `VERIFICATION_STRATEGY.md`. The mutation
framework (`mutation/framework.py`) has an `equivalent=True` field on
`Mutant` specifically to record a reviewed-and-rejected idea like these
without running or scoring it, for exactly this situation.

## Other notable findings (not on the required list, kept for completeness)

- **UART `send_byte()` busy-visibility race (Phase 2):** `tx_busy`
  becomes observable one cycle *after* the triggering write returns, not
  on the same cycle -- found because `wait_idle()`, called immediately
  after `send_byte()`, raced past the still-0-looking bus and returned
  "already idle" without actually waiting for the frame. Fixed by having
  `send_byte()` itself wait for `tx_busy` to rise before returning. The
  identical class of bug reappeared in APB's `ApbDriver` (Phase 5) for
  `busy_o`, and had to be independently found and fixed there too.
- **The scoreboard "ordering paradox" for polling reads (Phase 2, Phase
  5):** a reference model can only predict a status-poll's result if it
  already knows whether the awaited event happened -- which is precisely
  what polling exists to discover. Resolved by making polling loops
  (`wait_idle`, `wait_busy_clear`) intentionally unchecked/black-box,
  and asserting only on the final, post-poll state, which the model
  *can* correctly predict.
- **`wait_busy_clear()` polling over the real APB bus (Phase 5):** an
  early version polled `STATUS` via real APB reads. The monitor observes
  *every* bus transaction unconditionally and feeds it to the
  scoreboard; since these polling reads were never registered as
  "expected," they showed up as unmatched transactions and
  desynchronized the scoreboard's entire expected queue. Fixed by
  polling the `busy_o` observability port directly instead -- a
  deliberate choice to use a debug signal for pure test *synchronization*
  while keeping actual correctness checking (scoreboard, checkers) fully
  black-box.
- **A scheduling race between two independent `busy_o` watchers (Phase
  5):** `wait_busy_clear()` and `ApbLatencyChecker` both poll the same
  signal as separate cocotb tasks; nothing guarantees which one's
  continuation the scheduler runs first on the edge `busy_o` drops. This
  could silently produce `ops_checked=0` with no error -- a
  false-confidence bug, since "no violations" trivially holds when
  nothing was measured at all. Fixed with a settle margin in
  `wait_busy_clear()`, and every test that triggers a real operation now
  explicitly asserts the latency checker actually measured it, rather
  than trusting the mechanism silently.
- **`cocotb-coverage`'s `CoverPoint` on a zero-argument function (Phase
  3):** raises `IndexError` internally on a truly zero-argument sampled
  function, confirmed by isolated reproduction outside cocotb entirely.
  Worked around by giving every `CoverPoint` at least one positional
  argument, even where there is nothing meaningful to vary.
- **A Verible lint fix that made things worse (Phase 5):** giving
  `apb_regblock.v`'s address `localparam`s an explicit `logic [7:0]` type
  (to fix an "explicit-parameter-storage-type" finding) triggered a
  *different* Verible rule (parameter naming convention) that would have
  required abandoning the `ALL_CAPS_WITH_UNDERSCORES` convention used
  consistently everywhere else in the project, including UART's own
  `localparam`s. Reverted; documented as a deliberate trade-off rather
  than chased further.
- **An unreproduced stale-build anomaly, observed once (Phase 8):** during
  Phase 8's README-command verification, running `make MODULE=test_uart_tx_coverage`
  directly after a full `python run_regression.py` run -- with no
  intervening `make clean` -- once produced 3 false scoreboard failures
  whose signature (segment 9, the stop bit, stuck at 0 for the full bit
  period) matched a known mutant's defect exactly, even though `uart_tx.v`
  was independently confirmed byte-identical to golden RTL at the time
  (`diff` against `uart_tx_golden.v`, and `git status`, both clean). This
  is consistent with GNU Make reusing a stale compiled `sim_build/sim.vvp`
  left over from mutation testing's last mutant, since Make's rebuild
  decision is based on `uart_tx.v`'s mtime (unchanged for days) versus the
  compiled binary's mtime, not on which RTL was actually last compiled
  into it. However, three deliberate follow-up attempts to reproduce this
  exact sequence -- two runs of `mutation_suite.py` followed immediately
  by the same coverage command, and one full `run_regression.py` followed
  immediately by the same command -- all passed cleanly (4/4). The
  hypothesis above is plausible and consistent with the one observed
  failure, but is **not confirmed** as the root cause, since it could not
  be reliably reproduced to verify it. Rather than claim a fix for a
  mechanism that isn't confirmed, or silently ignore an observed false
  failure, the defensive mitigation actually applied is procedural: every
  individual-DUT command in `README.md` now reads `make clean && make
  MODULE=...` rather than bare `make MODULE=...`, matching the convention
  `mutation/framework.py` already uses internally for exactly this
  reason. If this resurfaces and becomes reproducible, the next step
  would be instrumenting `_run_make`'s restore step directly rather than
  inferring from symptoms.
- **Hand-driving Yosys without SymbiYosys (Phase 7):** a first attempt at
  formal used `yosys -p "... sat -verify ..."` directly, skipping `sby`
  entirely. Default optimization passes silently stripped the very
  assertion cell being checked, so the run reported success while
  checking nothing. This is why every formal property in this project
  goes through real `sby`, not a hand-rolled substitute -- confirmed by
  directly observing the failure mode, not by assuming `sby` was
  necessary in advance.
