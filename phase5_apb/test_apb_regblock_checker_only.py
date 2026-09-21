"""Isolation test: the APB protocol checker only, no scoreboard
assertion. Exists specifically to measure the checker's own detection
power for mutation_suite.py, independent of the scoreboard -- same
purpose as phase1_uart/test_uart_tx_checker_only.py.
"""

import cocotb

from apb_env import setup


@cocotb.test()
async def test_apb_checker_only(dut):
    driver, scoreboard, monitor, checker, latency_checker = await setup(dut, use_latency_checker=False)

    # Enough varied traffic to exercise SETUP->ACCESS sequencing,
    # stability, and PREADY for both directions, gapped and back-to-back
    # -- deliberately not registering scoreboard expectations (this test
    # asserts only on the checker).
    await driver.write(0x08, 0x11, idle_cycles=2)
    await driver.write(0x08, 0x22, idle_cycles=0)  # back-to-back
    await driver.read(0x08, idle_cycles=2)
    await driver.read(0x00, idle_cycles=0)  # back-to-back
    await driver.write(0x04, 0xFF, idle_cycles=1)  # illegal at the register-map level,
    await driver.read(0x0C, idle_cycles=1)  # but bus-protocol-legal -- not this checker's concern

    monitor.stop()
    checker.stop()
    cycles_checked, violations = checker.result()
    assert cycles_checked > 0, "checker did not observe any cycles"
    assert not violations, "Protocol checker reported violations:\n" + "\n".join(
        f"  cycle {v.cycle}: [{v.rule}] {v.detail}" for v in violations
    )
    print(f"PASSED: protocol checker observed {cycles_checked} cycles with no violations")
