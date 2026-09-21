"""Isolation test: the protocol checker only, with no scoreboard assertion.

Exists specifically to measure the checker's *own* detection power for
run_mutants_checker.py, independent of the scoreboard and independent of
UartTxDriver.wait_idle()'s own defensive timeout (which could otherwise
mask whether the checker itself catches a stuck-busy-style mutant). A
single byte is sent and then a fixed number of cycles are awaited
directly -- deliberately not calling driver.wait_idle() -- so a hung DUT
cannot be rescued by anything other than the checker's fixed-size sampling
window (see uart_env/checker.py for why that window is bounded by
construction, not by a "while busy" loop).
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

from uart_env import UartTxDriver, UartTxProtocolChecker


@cocotb.test()
async def test_uart_tx_checker_only(dut):
    cocotb.start_soon(Clock(dut.clk, 1, unit="ns").start())
    driver = UartTxDriver(dut)
    checker = UartTxProtocolChecker(dut, driver.clks_per_bit)
    checker.start()
    await driver.reset()

    dut.tx_data.value = 0x55
    dut.tx_start.value = 1
    await ClockCycles(dut.clk, 1)
    dut.tx_start.value = 0

    # Fixed bound, well past one legitimate frame (10*CLKS_PER_BIT=40 here)
    # -- not driver.wait_idle(), see module docstring.
    await ClockCycles(dut.clk, 60)

    checker.stop()
    checked, violations = checker.result()
    assert checked >= 1, "checker did not observe any frame"
    assert not violations, "Protocol checker reported violations:\n" + "\n".join(
        f"  frame {v.frame_index}: [{v.rule}] {v.detail}" for v in violations
    )
    print(f"PASSED: checker observed {checked} frame(s) with no protocol violations")
