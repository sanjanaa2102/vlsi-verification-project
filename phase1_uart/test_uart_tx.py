"""Directed regression for uart_tx, built on the uart_env driver / monitor /
scoreboard architecture (see uart_env/ and VERIFICATION_PLAN.md).

This module is what run_mutants.py exercises by default (MODULE=test_uart_tx
in the Makefile) -- its role in the mutation-testing framework is unchanged
by this refactor, only its internal structure is.
"""

import cocotb
from cocotb.triggers import ClockCycles

from uart_env import finish, setup


@cocotb.test()
async def test_uart_tx_basic(dut):
    """Feature: correct 8N1 framing and data value for a range of bytes.
    Check: scoreboard compares monitor-decoded bytes (and per-segment
    cycle-accurate timing) against the reference model for each byte."""
    driver, scoreboard, monitor = await setup(dut)
    for val in [0x00, 0xFF, 0xA5, 0x55, 0x01]:
        scoreboard.expect(val)
        await driver.send_byte(val)
        await driver.wait_idle()
        await ClockCycles(dut.clk, 2)
    checked = await finish(driver, scoreboard, monitor)
    assert checked == 5, f"expected 5 transactions checked, got {checked}"
    print("PASSED: all bytes transmitted correctly")


@cocotb.test()
async def test_uart_tx_timing(dut):
    """Feature: every bit period (start, 8 data bits, stop) holds a
    constant value for exactly CLKS_PER_BIT cycles. Check: the monitor
    samples every cycle of every segment (no fixed-offset assumption);
    the scoreboard fails if any segment is non-constant."""
    driver, scoreboard, monitor = await setup(dut)
    scoreboard.expect(0x55)
    await driver.send_byte(0x55)
    checked = await finish(driver, scoreboard, monitor)
    assert checked == 1, f"expected 1 transaction checked, got {checked}"
    print(
        f"PASSED: all 10 segments (start + 8 data + stop) held for exactly "
        f"{driver.clks_per_bit} cycles"
    )
