"""Shared per-test wiring for apb_regblock testbenches: starts the clock,
builds a driver/monitor/scoreboard/checker/latency-checker set, and tears
it down cleanly -- same pattern as phase1_uart/uart_env/harness.py.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

from .checker import ApbProtocolChecker
from .driver import ApbDriver
from .latency_checker import ApbLatencyChecker
from .monitor import ApbMonitor
from .scoreboard import ApbScoreboard

OP_LATENCY = 4  # must match apb_regblock's OP_LATENCY parameter default


async def setup(dut, use_checker=True, use_latency_checker=True):
    cocotb.start_soon(Clock(dut.PCLK, 1, unit="ns").start())
    driver = ApbDriver(dut)
    scoreboard = ApbScoreboard()
    monitor = ApbMonitor(dut, scoreboard.check_transaction)
    monitor.start()

    checker = ApbProtocolChecker(dut) if use_checker else None
    if checker is not None:
        checker.start()

    latency_checker = ApbLatencyChecker(dut, OP_LATENCY) if use_latency_checker else None
    if latency_checker is not None:
        latency_checker.start()

    await driver.reset()
    return driver, scoreboard, monitor, checker, latency_checker


async def finish(driver, scoreboard, monitor, checker=None, latency_checker=None, check_scoreboard=True):
    await ClockCycles(driver.dut.PCLK, 2)
    monitor.stop()

    checked, errors = scoreboard.result()
    if check_scoreboard:
        assert not errors, "Scoreboard reported errors:\n" + "\n".join(errors)

    if checker is not None:
        checker.stop()
        _cycles_checked, violations = checker.result()
        assert not violations, "Protocol checker reported violations:\n" + "\n".join(
            f"  cycle {v.cycle}: [{v.rule}] {v.detail}" for v in violations
        )

    if latency_checker is not None:
        latency_checker.stop()
        _ops_checked, lat_violations = latency_checker.result()
        assert not lat_violations, "Latency checker reported violations:\n" + "\n".join(
            v.detail for v in lat_violations
        )

    return checked
