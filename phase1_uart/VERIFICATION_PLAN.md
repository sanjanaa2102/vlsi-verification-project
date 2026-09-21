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
| 9 | Testbench itself is capable of detecting injected RTL bugs (mutation testing) | `run_mutants.py` against `test_uart_tx.py` | Mutation score: mutants CAUGHT / total | -- |
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

## Scoreboard vs. protocol checker: measured, not assumed, distinction

Both mechanisms are attached to every test via the shared harness. Their
detection power was measured in isolation:

| Mutant | Scoreboard (`run_mutants.py`) | Checker alone (`run_mutants_checker.py`) |
|---|---|---|
| mutant1_stop_bit_polarity | CAUGHT | CAUGHT |
| mutant2_dropped_last_bit | CAUGHT | CAUGHT |
| mutant3_short_start_bit | CAUGHT | CAUGHT |
| mutant4_busy_stuck_high | CAUGHT (also independently by `UartTxDriver.wait_idle`'s bounded timeout) | CAUGHT |
| mutant5_msb_first_bug | CAUGHT | **SURVIVED** |
| mutant6_short_data_bits | CAUGHT | CAUGHT |

mutant5 is the clean demonstration of the categorical difference: it
reorders which bits get sent (MSB-first instead of LSB-first) while
leaving every timing/framing property perfectly correct -- 10
well-formed, correctly-timed segments, right start/stop bits, right
`tx_busy` duration. A checker that never knows the intended byte has no
way to see this; only the scoreboard, which knows the expected value, can.

**Is the current mutant set still sufficiently discriminating?** For the
*combined* environment (scoreboard + checker together, as every test now
runs it), yes -- all 6 mutants are still caught, so nothing currently
regresses undetected. But the set does not include a mutant that isolates
the checker's *unique* value the way mutant5 isolates the scoreboard's:
every current timing/framing mutant (1,2,3,4,6) also happens to corrupt
the decoded byte value, so the scoreboard alone already catches all of
them too -- the checker's contribution on this set is fully redundant
with the scoreboard's. A mutant that broke *only* inter-frame timing
(e.g. required extra idle cycles between frames that the driver's
`wait_idle` already tolerates) without corrupting any single frame's data
would be a natural way to demonstrate a checker-exclusive catch -- noted
as an observation, not implemented, since manufacturing a mutant just to
move this metric would be the artificial modification this phase was
explicitly told not to do.

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
  regenerating the 6 single-bug mutant files to preserve the "exactly one
  injected difference from golden" property, which is a mutation-testing-
  framework change, not a verification-architecture one.

## How to run

```bash
# Existing directed regression (also what run_mutants.py exercises):
make

# Phase 2 coverage regression (separate module, not part of run_mutants.py):
make MODULE=test_uart_tx_coverage
cat sim_build/coverage.yml   # exported coverage report

# Phase 3 constrained-random regression:
make MODULE=test_uart_tx_random
cat sim_build/coverage_random.yml

# Reproduce a specific random run/failure (seed is logged by every run):
make MODULE=test_uart_tx_random COCOTB_RANDOM_SEED=<seed>

# Protocol-checker-only isolation test:
make MODULE=test_uart_tx_checker_only

# Mutation testing:
python run_mutants.py            # scoreboard-based (test_uart_tx.py), unchanged
python run_mutants_checker.py    # protocol-checker-only (test_uart_tx_checker_only.py)
```
