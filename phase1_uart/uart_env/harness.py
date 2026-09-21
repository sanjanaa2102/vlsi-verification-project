"""Shared per-test wiring for uart_tx testbenches: starts the clock, builds
a driver/monitor/scoreboard triple, and tears it down cleanly. Factored out
so every test module builds the environment identically instead of each
re-implementing it."""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

from .driver import UartTxDriver
from .monitor import UartTxMonitor
from .scoreboard import UartTxScoreboard


async def setup(dut):
    cocotb.start_soon(Clock(dut.clk, 1, unit="ns").start())
    driver = UartTxDriver(dut)
    scoreboard = UartTxScoreboard()
    monitor = UartTxMonitor(dut, driver.clks_per_bit, scoreboard.check_transaction)
    monitor.start()
    await driver.reset()
    return driver, scoreboard, monitor


async def finish(driver, scoreboard, monitor):
    await driver.wait_idle()
    await ClockCycles(driver.dut.clk, 2)
    monitor.stop()
    checked, errors = scoreboard.result()
    assert not errors, "Scoreboard reported errors:\n" + "\n".join(errors)
    return checked
