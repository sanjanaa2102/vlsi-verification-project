"""Phase 2 coverage regression for uart_tx.

Run separately from test_uart_tx.py (not part of run_mutants.py's default
target) so the existing mutation-testing baseline is untouched by this
addition. Stimulus is still directed -- deliberately chosen to hit every
bin defined in uart_env/coverage.py -- rather than constrained-random,
which is planned for a later phase. See VERIFICATION_PLAN.md for the
feature/test/check/coverage traceability this test implements.
"""

import cocotb
from cocotb.triggers import ClockCycles

from uart_env import coverage, finish, setup
from uart_env.reference_model import byte_class

# (byte value, framing mode). Chosen so every (data class x mode) cross bin
# in uart_env.coverage is hit exactly once, one byte per class per mode.
STIMULUS = [
    (0x00, "gapped"),
    (0x00, "back_to_back"),
    (0xFF, "gapped"),
    (0xFF, "back_to_back"),
    (0x55, "gapped"),
    (0xAA, "back_to_back"),
    (0x01, "gapped"),
    (0x80, "back_to_back"),
    (0x3C, "gapped"),
    (0xC3, "back_to_back"),
]


@cocotb.test()
async def test_uart_tx_coverage_sweep(dut):
    """Feature: every (byte-pattern class x framing mode) combination
    transmits correctly. Check: scoreboard, as in test_uart_tx.py. Coverage:
    samples top.tx_data_class_x_mode once per transaction."""
    driver, scoreboard, monitor = await setup(dut)

    for byte_val, mode in STIMULUS:
        assert byte_class(byte_val) in (
            "zero",
            "all_ones",
            "alternating",
            "walking_one",
            "other",
        )
        idle_cycles = 0 if mode == "back_to_back" else 2
        scoreboard.expect(byte_val)
        await driver.send_byte(byte_val, idle_cycles=idle_cycles)
        coverage.sample_transaction(byte_val, mode)

    checked = await finish(driver, scoreboard, monitor)
    assert checked == len(STIMULUS), f"expected {len(STIMULUS)} transactions, got {checked}"
    print(f"PASSED: {checked} transactions across all data-class x mode bins")


@cocotb.test()
async def test_uart_tx_reset_mid_frame(dut):
    """Feature: the DUT recovers cleanly from a reset asserted partway
    through a frame. Check: tx_busy/tx_serial return to idle levels, the
    aborted frame is not scored against any expected byte (the monitor
    marks it aborted), and a normal transmission afterward still works.
    Coverage: samples top.reset_mid_transmission once."""
    driver, scoreboard, monitor = await setup(dut)

    # Start a frame directly (bypassing scoreboard.expect -- this frame is
    # deliberately never going to complete) and interrupt it mid-data.
    dut.tx_data.value = 0x77
    dut.tx_start.value = 1
    await ClockCycles(dut.clk, 1)
    dut.tx_start.value = 0
    await ClockCycles(dut.clk, 10)  # partway into the data bits
    await driver.pulse_reset(hold_cycles=2)
    await ClockCycles(dut.clk, 2)

    assert int(dut.tx_busy.value) == 0, "tx_busy should be low after a mid-frame reset"
    assert int(dut.tx_serial.value) == 1, "tx_serial should return to idle high after reset"
    coverage.sample_reset_mid_transmission("occurred")

    # DUT must still work correctly afterward.
    scoreboard.expect(0x99)
    await driver.send_byte(0x99)

    checked = await finish(driver, scoreboard, monitor)
    assert checked == 1, f"expected 1 post-reset transaction checked, got {checked}"
    print("PASSED: DUT recovered from a mid-frame reset and transmitted correctly afterward")


@cocotb.test()
async def test_uart_tx_coverage_report(dut):
    """Not a functional check -- cocotb runs @cocotb.test() functions in
    the order they are defined in the file, so this runs last within this
    module and reports/exports the coverage accumulated by the two tests
    above (coverage_db is a process-global singleton that persists across
    tests in the same simulation run). Fails loudly if a bin was missed."""
    coverage.report(cocotb.log.info)
    coverage.export("sim_build/coverage.yml")
    pct = coverage.overall_percentage()
    cocotb.log.info(f"Overall functional coverage: {pct:.1f}%")
    assert pct == 100.0, f"expected 100% coverage from the directed sweep, got {pct:.1f}%"
