# UART TX Verification Plan

Scope: `uart_tx.v` (8N1, configurable `CLKS_PER_BIT`). Architecture:
`uart_env/` provides a driver (stimulus only), a monitor (passive,
autonomous decode of DUT outputs -- independent of what the driver
intended), a scoreboard (the only place a *data-value* pass/fail
comparison happens, against `reference_model.py`), a protocol checker
(the only place a *framing/timing* invariant is checked, independent of
any expected byte -- see `uart_env/checker.py`), a constrained-random
stimulus generator (`uart_env/sequences.py`), and a functional coverage
model (`coverage.py`, built on `cocotb-coverage`).

## Traceability: feature -> test -> check -> coverage

| # | Feature / requirement | Test(s) | Check mechanism | Coverage |
|---|---|---|---|---|
| 1 | Correct 8N1 framing and data value, LSB first, for arbitrary byte values | `test_uart_tx.test_uart_tx_basic` | Scoreboard compares monitor-decoded byte + per-segment samples against `reference_model.expected_frame_bits` | -- |
| 2 | Every bit period (start, 8 data, stop) holds a constant value for exactly `CLKS_PER_BIT` cycles | `test_uart_tx.test_uart_tx_timing` | Monitor samples every clock cycle of every segment (no fixed-time-offset assumption); scoreboard fails on any non-constant segment | -- |
| 3 | `tx_busy` is asserted for the full frame and deasserts on the cycle the stop bit's last cycle commits | `test_uart_tx.*`, `test_uart_tx_coverage.*` (via `Transaction.busy_ok`) | Scoreboard checks `busy_ok` on every transaction | -- |
| 4 | Structurally distinct byte patterns (all-zero, all-one, toggling, single-bit-set, other) all transmit correctly | `test_uart_tx_coverage.test_uart_tx_coverage_sweep` | Scoreboard (same mechanism as #1) | `top.tx_data_class` (5 bins) |
| 5 | Framing works both when a new frame starts immediately after the previous one (back-to-back) and after idle time (gapped) | `test_uart_tx_coverage.test_uart_tx_coverage_sweep` | Scoreboard | `top.tx_mode` (2 bins) |
| 6 | Every byte-pattern class transmits correctly under both framing modes, not just some combinations | `test_uart_tx_coverage.test_uart_tx_coverage_sweep` | Scoreboard | `top.tx_data_class_x_mode` (10 cross bins) |
| 7 | A reset asserted mid-frame is handled safely: DUT returns to idle (`tx_busy=0`, `tx_serial=1`) and transmits correctly afterward | `test_uart_tx_coverage.test_uart_tx_reset_mid_frame` | Direct assertions on post-reset DUT state, plus scoreboard check on the following transmission; the aborted frame itself is excluded from scoreboard comparison (monitor marks it `aborted`) | `top.reset_mid_transmission` (1 bin) |
| 8 | A broken DUT (e.g. `tx_busy` stuck high) fails the regression cleanly and quickly rather than hanging it | `run_mutants.py` / `mutant4_busy_stuck_high` | `UartTxDriver.wait_idle` bounded timeout (`max_cycles`); independently, `UartTxProtocolChecker`'s fixed-size sampling window (see #10-12) | -- (regression-robustness check, not a functional-coverage bin) |
| 9 | Testbench itself is capable of detecting injected RTL bugs (mutation testing) | `mutation_suite.py` (generalized, 3 mechanisms x 9 mutants) -- `run_mutants.py`/`run_mutants_checker.py` preserved unchanged as single-mechanism entry points | Mutation score: mutants CAUGHT / total, attributed per mechanism | -- |
| 10 | Start bit is always 0, stop bit is always 1, every segment holds a constant value for `CLKS_PER_BIT` cycles, and a frame's `tx_busy`-high duration is always exactly `10*CLKS_PER_BIT` cycles -- **for any byte value**, checked independently of what was actually sent | `test_uart_tx_checker_only`, and (attached by default via the shared harness) every other test in this plan | `UartTxProtocolChecker`: a cocotb concurrent checker, not the scoreboard -- see "Why a Python checker, not SVA" below | -- (structural/timing invariant, not a functional-coverage bin) |
| 11 | The DUT transmits correctly under a constrained mix of byte values, idle-gap timings, and back-to-back chain lengths, including corner cases no directed test covers (3+-frame chains, varied gap lengths) | `test_uart_tx_random.test_uart_tx_random_sweep` | Scoreboard + protocol checker together (both attached via the shared harness) | `top.idle_gap_class` (3 bins), `top.back_to_back_chain_length` (2 bins) |
| 12 | A failing random-test transaction is reproducible without re-deriving it | `test_uart_tx_random.*` | `COCOTB_RANDOM_SEED` (cocotb logs it every run) reproduces the whole sequence byte-for-byte (verified); every transaction is also individually logged (index, byte, idle_cycles) as it is driven | -- |

## Why a Python (cocotb) checker, not SVA

Verified directly (not assumed): Icarus Verilog 12.0 fails to parse
concurrent/temporal SystemVerilog assertions (`property`, `assert
property`, `##`, `|->` sequences all error out). Simple *immediate*
assertions (`assert (expr) else ...`) do compile, but the invariants that
matter here -- "this segment is constant for exactly `CLKS_PER_BIT`
cycles", "the frame takes exactly `10*CLKS_PER_BIT` cycles" -- are
inherently temporal and can't be expressed as a single-cycle immediate
assertion without re-implementing cycle-history tracking inside Verilog,
at which point there's no benefit over doing it in Python. Given the
verified limits of this specific free/no-billing toolchain, a cocotb
concurrent checker (`uart_env/checker.py`) is the strongest mechanism
actually available -- not a default choice, a constrained one.

## Phase 4: a generalized, DUT-agnostic mutation framework

`mutation/` (top-level, sibling to `phase1_uart/`) is a small, generic
engine with no UART knowledge: `Mutant` and `Mechanism` data classes, a
`run_suite()` that drives `make clean && make VERILOG_SOURCES=<mutant>
MODULE=<mechanism>` in any DUT directory and classifies CAUGHT/SURVIVED
per mechanism from cocotb's own `FAIL=<n>` summary line, and a reporter
producing total/caught/surviving/score, a per-defect-category breakdown,
and a per-mutant mechanism-attribution table, plus a JSON export
(`sim_build/mutation_report.json`). `phase1_uart/mutation_suite.py` is
the UART-specific manifest (the mutant list below, plus which cocotb test
module each verification mechanism corresponds to) built on that engine.
A future DUT (e.g. the planned APB-Lite environment) reuses `mutation/`
as-is by writing its own manifest -- no runner code to duplicate.

`run_mutants.py` and `run_mutants_checker.py` are preserved completely
unchanged (still directly runnable, still reproducing the exact same
scoreboard-only and checker-only results as Phase 3) -- the generalized
system is additive, not a replacement.

### Mutant review: defect categories, and what was missing

Reviewing the original 6 mutants by their actual RTL diff (not by name)
found they cover 5 defect categories: polarity/constant inversion
(mutant1), off-by-one/boundary in a bit counter (mutant2), off-by-one/
boundary in a timing counter, short direction only (mutant3, mutant6),
a stuck-at-style incorrect constant (mutant4), and an indexing/bit-order
bug (mutant5). Three realistic, currently-missing categories were
identified and added:

| New mutant | Defect category | Models |
|---|---|---|
| `mutant7_incomplete_reset` | reset / initialization | Reset stops forcing the FSM back to `IDLE` -- a classic "partial reset" mistake (some registers cleared, the state register forgotten) |
| `mutant8_unlatched_data` | data capture / latching | `DATA` state reads the live `tx_data` input instead of the captured `data_reg` -- a classic "forgot to use the registered value" mistake |
| `mutant9_long_start_bit` | off-by-one / boundary (timing, **long** direction) | START segment held one cycle too *long* instead of too short -- the existing timing mutants (3, 6) only ever tested the short direction |

One candidate mutant was reviewed and **deliberately not added**:
removing `bit_idx<=0`/`busy_reg<=0` from the `rst` branch. Tracing the
RTL shows both are unconditionally re-assigned by the `IDLE` state's own
case branch on the very next cycle in every reachable scenario, so no
test could ever distinguish this from golden RTL -- it is a true
equivalent mutant. Adding it would only inflate the mutant count without
adding real signal, which is exactly what this phase was told not to do.
The framework supports marking a mutant `equivalent=True` (excluded from
scoring, documented with a reason) for exactly this situation in a future
DUT; none of the 9 UART mutants need it.

### Surviving mutants: investigated, and what was actually wrong

Both mutant7 and mutant8 **initially survived both existing mechanisms**
(scoreboard via `test_uart_tx`, checker via `test_uart_tx_checker_only`).
Investigating rather than dismissing this surfaced two distinct, genuine
issues -- one in the mutation *suite's* mechanism list, one a real bug in
`uart_env`:

- **mutant7** turned out to be a suite-configuration gap, not an
  environment gap: `test_uart_tx_coverage.test_uart_tx_reset_mid_frame`
  already exercises reset-after-leaving-IDLE and, once added as a third
  mechanism (`coverage_directed`), does catch it. `test_uart_tx` alone
  never resets after `IDLE` (every one of its tests only resets once, at
  the very start, when the state register is already `IDLE` from its
  Verilog initial value) -- it structurally cannot exercise this defect
  class, which is exactly why the mechanism was missing, not the check.

  Investigating this *also* found a real, unbounded-loop bug: with
  mutant7 applied, `test_uart_tx_coverage`'s reset-mid-frame test hung
  the whole regression instead of failing. `UartTxDriver.send_byte()`'s
  "wait for `tx_busy` to rise" loop (added in Phase 2) had no bound --
  once the FSM drifts away from `IDLE` without going through it again,
  `tx_busy` can never legitimately rise in response to a new `tx_start`
  (only the `IDLE` branch checks `tx_start` at all), so the loop spun
  forever. Fixed with the same bounded-timeout pattern already used in
  `wait_idle()` (`uart_env/driver.py`): a clean `AssertionError` after
  200 cycles instead of a hang. Verified this doesn't affect golden RTL
  (full regression still passes) and that the mutant now fails cleanly
  and quickly.

- **mutant8 was a genuine, structural verification gap.** No test in
  this project -- directed, coverage, or random -- ever changes
  `tx_data` during an active frame, so a DUT that read `tx_data` live
  instead of capturing it once into `data_reg` was, by construction,
  indistinguishable from a correct one to every existing test. This is
  exactly the kind of gap Phase 4 was meant to surface. Fixed by adding
  one new targeted test, `test_uart_tx_coverage.test_uart_tx_data_latched`:
  send a byte, change `tx_data` to a decoy value partway through the
  frame (well past the start bit), and confirm the transmitted byte is
  still the original -- confirmed to fail against mutant8 (`0xc6`
  received instead of the expected `0x3a`, the decoy bleeding into the
  transmission) and to pass against golden RTL. No other test or
  architecture code was changed to achieve this catch.

### Final result (measured, not assumed)

| Mutant | Defect category | `coverage_directed` | `protocol_checker` | `scoreboard` | Overall |
|---|---|---|---|---|---|
| mutant1_stop_bit_polarity | polarity / constant inversion | CAUGHT | CAUGHT | CAUGHT | CAUGHT |
| mutant2_dropped_last_bit | off-by-one / boundary (bit count) | CAUGHT | CAUGHT | CAUGHT | CAUGHT |
| mutant3_short_start_bit | off-by-one / boundary (timing, short) | CAUGHT | CAUGHT | CAUGHT | CAUGHT |
| mutant4_busy_stuck_high | stuck-at / incorrect constant | CAUGHT | CAUGHT | CAUGHT | CAUGHT |
| mutant5_msb_first_bug | indexing / bit-order logic | CAUGHT | **SURVIVED** | CAUGHT | CAUGHT |
| mutant6_short_data_bits | off-by-one / boundary (timing, short) | CAUGHT | CAUGHT | CAUGHT | CAUGHT |
| mutant7_incomplete_reset | reset / initialization | CAUGHT | **SURVIVED** | **SURVIVED** | CAUGHT |
| mutant8_unlatched_data | data capture / latching | CAUGHT | **SURVIVED** | **SURVIVED** | CAUGHT |
| mutant9_long_start_bit | off-by-one / boundary (timing, long) | CAUGHT | CAUGHT | CAUGHT | CAUGHT |

**Combined mutation score: 9/9 = 100%.** Per-mechanism:
`coverage_directed` alone 9/9 (100%), `scoreboard` alone 7/9 (77.8%),
`protocol_checker` alone 6/9 (66.7%). mutant5 remains the clean,
unchanged demonstration that the checker categorically cannot catch a
pure data-value bug (correct timing, wrong bits) -- only the scoreboard
can, since only it knows the expected byte. This 100% was earned by
fixing one real environment gap and one real robustness bug, not by
weakening a mutant or inflating the count -- the two mutants that
initially survived are documented above with exactly what was found and
changed.

**Is the mutant set still sufficiently discriminating?** With all 9
caught by the combined environment and each of the 8 defect categories
represented by at least one mutant, yes for now. `protocol_checker`
alone (66.7%) is the weakest individual mechanism, which is expected and
correct, not a gap: 3 of the 9 mutants (5, 7, 8) are defects the checker
is *designed* not to see (data-value, or scenarios outside its own
test's scope), not defects it fails to detect within its actual
responsibility.

## Is the Phase 2 100% coverage number still meaningful?

Measured, not assumed: after adding the two Phase 3 CoverPoints
(`idle_gap_class`, `back_to_back_chain_length`) to the same `coverage.py`
module, re-running `test_uart_tx_coverage.py` (Phase 2's directed sweep)
in isolation shows the 4 bins/cross it actually drives
(`tx_data_class`, `tx_mode`, their cross, `reset_mid_transmission`) still
at 100%, while the *global* aggregate for that module's own process drops
to 78.3% -- because importing `uart_env.coverage` registers the two new
Phase 3 points in every process regardless of whether that module samples
them. This is not a regression; it's process-scoped `coverage_db`
behavior (`cocotb-coverage` is a per-simulation-process singleton), and
each module now asserts closure only on the bins it owns (see
`coverage.bin_percentage`) rather than the global aggregate.

Substantively: yes, the old 100% is still meaningful for what it always
measured (every structural byte-pattern class transmits correctly under
both framing modes) -- but it was never a *fine-grained* number. The
`tx_data_class` bins are broad structural categories (e.g. "other" covers
246 possible byte values as a single bin), closeable by a handful of
directed sends, so a coarse "other" byte and a random one both land in
the same already-covered bin without adding new signal. The genuinely new
signal from constrained-random testing -- the idle-gap magnitude actually
used, and back-to-back chains longer than 2 frames -- is exactly what the
two new Phase 3 axes measure, and those are the numbers that only became
meaningful once random stimulus existed to vary them.

## What is intentionally out of scope for this phase

- **UART RX / full-duplex loopback.** Not yet implemented.
- **`CLKS_PER_BIT` elaboration-time sweep** (i.e. re-running the
  regression built with a different `CLKS_PER_BIT` value). Verified not to
  be a clean drop-in: overriding `COMPILE_ARGS` on the `make` command line
  to pass `-Puart_tx.CLKS_PER_BIT=8` clobbers the Makefile-managed
  inclusion of `sim_build/cmds.f` and breaks the simulator's precision
  setup (reproduced: `ValueError: Bad period: Unable to accurately
  represent 1(ns)...`). Fixing this safely means editing
  `Makefile.icarus` internals, which is out of scope here.
  "Timing/configuration variation" in this phase is instead satisfied by
  idle-gap timing (`uart_env/sequences.py`), which is fully in-scope and
  well-supported.
- **RTL lint findings** (`uart_tx.v`, flagged by Verible: two untyped
  parameters, one missing `case` default, one missing trailing newline)
  are still not fixed. Same reasoning as Phase 2: fixing them means
  regenerating all 9 single-bug mutant files to preserve the "exactly one
  injected difference from golden" property, which is a mutation-testing-
  framework change, not a verification-architecture one. (Note: the
  `case-missing-default` finding is itself a lint-level version of the
  same "incomplete handling of unreachable states" concern mutant7 probes
  at the reset level -- worth keeping in mind for a future phase that does
  take on the RTL cleanup.)

## How to run

```bash
# Existing directed regression (also what run_mutants.py exercises):
make

# Phase 2 coverage regression (also includes reset-mid-frame and, as of
# Phase 4, the tx_data-latching test):
make MODULE=test_uart_tx_coverage
cat sim_build/coverage.yml   # exported coverage report

# Phase 3 constrained-random regression:
make MODULE=test_uart_tx_random
cat sim_build/coverage_random.yml

# Reproduce a specific random run/failure (seed is logged by every run):
make MODULE=test_uart_tx_random COCOTB_RANDOM_SEED=<seed>

# Protocol-checker-only isolation test:
make MODULE=test_uart_tx_checker_only

# Mutation testing -- single-mechanism scripts (unchanged since Phase 3):
python run_mutants.py            # scoreboard-based (test_uart_tx.py)
python run_mutants_checker.py    # protocol-checker-only (test_uart_tx_checker_only.py)

# Mutation testing -- Phase 4 generalized suite (all 9 mutants x all 3
# mechanisms, with defect-category/mechanism-attribution report and a
# JSON export to sim_build/mutation_report.json):
python mutation_suite.py
```
