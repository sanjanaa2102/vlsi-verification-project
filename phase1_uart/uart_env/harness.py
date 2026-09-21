"""Shared per-test wiring for uart_tx testbenches: starts the clock, builds
a driver/monitor/scoreboard/checker set, and tears it down cleanly.
Factored out so every test module builds the environment identically
instead of each re-implementing it.

The protocol checker (uart_env.checker.UartTxProtocolChecker) is attached
by default alongside the scoreboard as of Phase 3: it is a genuinely
different, data-independent check (see checker.py for why), so running it
in every regression is real added coverage of protocol bugs, not just
scope creep. finish() reports scoreboard and checker failures separately
so it stays clear which mechanism caught what.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

from .checker import UartTxProtocolChecker
from .driver import UartTxDriver
from .monitor import UartTxMonitor
from .scoreboard import UartTxScoreboard


async def setup(dut, use_checker=True):
    cocotb.start_soon(Clock(dut.clk, 1, unit="ns").start())
    driver = UartTxDriver(dut)
    scoreboard = UartTxScoreboard()
    monitor = UartTxMonitor(dut, driver.clks_per_bit, scoreboard.check_transaction)
    monitor.start()
    checker = UartTxProtocolChecker(dut, driver.clks_per_bit) if use_checker else None
    if checker is not None:
        checker.start()
    await driver.reset()
    return driver, scoreboard, monitor, checker


async def finish(driver, scoreboard, monitor, checker=None, check_scoreboard=True):
    await driver.wait_idle()
    await ClockCycles(driver.dut.clk, 2)
    monitor.stop()

    checked, errors = scoreboard.result()
    if check_scoreboard:
        assert not errors, "Scoreboard reported errors:\n" + "\n".join(errors)

    if checker is not None:
        checker.stop()
        frames_checked, violations = checker.result()
        assert not violations, "Protocol checker reported violations:\n" + "\n".join(
            f"  frame {v.frame_index}: [{v.rule}] {v.detail}" for v in violations
        )

    return checked
