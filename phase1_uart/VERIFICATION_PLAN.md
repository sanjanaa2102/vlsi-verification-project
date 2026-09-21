# UART TX Verification Plan

Scope: `uart_tx.v` (8N1, configurable `CLKS_PER_BIT`). Architecture:
`uart_env/` provides a driver (stimulus only), a monitor (passive,
autonomous decode of DUT outputs -- independent of what the driver
intended), a scoreboard (the only place a pass/fail comparison happens,
against `reference_model.py`), and a functional coverage model
(`coverage.py`, built on `cocotb-coverage`).

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
| 8 | A broken DUT (e.g. `tx_busy` stuck high) fails the regression cleanly and quickly rather than hanging it | `run_mutants.py` / `mutant4_busy_stuck_high` | `UartTxDriver.wait_idle` bounded timeout (`max_cycles`) | -- (regression-robustness check, not a functional-coverage bin) |
| 9 | Testbench itself is capable of detecting injected RTL bugs (mutation testing) | `run_mutants.py` against `test_uart_tx.py` | Mutation score: mutants CAUGHT / total | -- |

## What is intentionally out of scope for this phase

- **Constrained-random stimulus generation.** Row 4-7 above use a
  deliberately broadened but still *directed* stimulus set, chosen to hit
  every defined coverage bin exactly. True constrained-random generation
  (with coverage-driven closure over a random seed sweep, rather than a
  hand-picked list) is planned for a later phase.
- **UART RX / full-duplex loopback.** Not yet implemented.
- **SVA / formal protocol assertions.** The monitor's cycle-accurate
  sampling plays the role of a timing checker today; dedicated assertions
  (and a formal property or two) are planned for a later phase.
- **RTL lint findings** (`uart_tx.v`, flagged by Verible: two untyped
  parameters, one missing `case` default, one missing trailing newline)
  are not fixed in this phase. Fixing them would require regenerating the
  6 single-bug mutant files to keep the "exactly one injected difference
  from golden" property intact, which is a mutation-testing-framework
  change, not a verification-architecture one -- deferred rather than
  bundled in here.

## How to run

```bash
# Existing directed regression (also what run_mutants.py exercises):
make

# Phase 2 coverage regression (separate module, not part of run_mutants.py):
make MODULE=test_uart_tx_coverage
cat sim_build/coverage.yml   # exported coverage report

# Mutation testing (unchanged):
python run_mutants.py
```
