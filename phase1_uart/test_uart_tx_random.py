"""Phase 3 constrained-random regression for uart_tx.

Run separately from test_uart_tx.py (run_mutants.py's target is
unchanged) so the Phase 1/2 mutation-testing baseline stays untouched by
this addition.

Reproducing a failure: cocotb seeds and logs Python's global `random`
module at the start of every run ("Seeding Python random module with
<seed>"). uart_env.sequences builds on that same global module, so a
failure is reproduced exactly with:

    make MODULE=test_uart_tx_random COCOTB_RANDOM_SEED=<seed from the log>

Every generated transaction is also logged individually (index, byte,
idle_cycles) as it is driven, so a failing run's log shows exactly which
transaction in the sequence triggered the failure without needing to
replay anything.
"""

import cocotb

from uart_env import coverage, finish, setup
from uart_env.reference_model import byte_class, gap_class
from uart_env.sequences import chain_lengths, gen_sequence


@cocotb.test()
async def test_uart_tx_random_sweep(dut):
    """Feature: the DUT transmits correctly under a constrained-random mix
    of byte values, idle-gap timings, and back-to-back chain lengths
    (including corner cases directed testing didn't cover: 3+-frame
    chains, small vs. large gaps). Check: scoreboard (data correctness)
    and protocol checker (framing/timing), both attached via the shared
    harness. Coverage: idle_gap_class and back_to_back_chain_length."""
    stimulus = gen_sequence(n_random_before=10, n_random_after=10)
    lengths = chain_lengths(stimulus)

    cocotb.log.info(
        f"Generated {len(stimulus)} transactions, {len(lengths)} back-to-back "
        f"chain(s) of length(s) {lengths}"
    )

    driver, scoreboard, monitor, checker = await setup(dut)

    for i, txn in enumerate(stimulus):
        byte_val, idle_cycles = txn["byte_val"], txn["idle_cycles"]
        cocotb.log.info(
            f"txn[{i}]: byte={byte_val:#04x} class={byte_class(byte_val)} "
            f"idle_cycles={idle_cycles} gap_class={gap_class(idle_cycles)}"
        )
        scoreboard.expect(byte_val)
        await driver.send_byte(byte_val, idle_cycles=idle_cycles)
        coverage.sample_idle_gap(idle_cycles)

    for length in lengths:
        coverage.sample_chain_length(length)

    checked = await finish(driver, scoreboard, monitor, checker)
    assert checked == len(stimulus), f"expected {len(stimulus)} transactions, got {checked}"
    print(f"PASSED: {checked} constrained-random transactions, chains={lengths}")


@cocotb.test()
async def test_uart_tx_random_coverage_report(dut):
    """Not a functional check -- runs last in this module (see
    test_uart_tx_coverage.py for why coverage_db is process-scoped and why
    this asserts closure only on the 2 points this module owns)."""
    coverage.report(cocotb.log.info)
    coverage.export("sim_build/coverage_random.yml")

    owned = ["top.idle_gap_class", "top.back_to_back_chain_length"]
    for name in owned:
        pct = coverage.bin_percentage(name)
        cocotb.log.info(f"{name}: {pct:.1f}%")
        assert pct == 100.0, f"expected 100% coverage on {name}, got {pct:.1f}%"

    cocotb.log.info(f"Overall functional coverage (this module only): {coverage.overall_percentage():.1f}%")
