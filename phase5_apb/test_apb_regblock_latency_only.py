"""Isolation test: the latency checker only, no scoreboard assertion.
Exists specifically to measure ApbLatencyChecker's own detection power
for mutation_suite.py, independent of the scoreboard.
"""

import cocotb

from apb_env import setup


@cocotb.test()
async def test_apb_latency_only(dut):
    driver, scoreboard, monitor, checker, latency_checker = await setup(dut, use_checker=False)

    await driver.write(0x00, 0x01)  # ENABLE
    await driver.write(0x00, 0x02)  # START
    await driver.wait_busy_clear()

    monitor.stop()
    latency_checker.stop()
    ops_checked, violations = latency_checker.result()
    assert ops_checked == 1, f"expected 1 measured operation, got {ops_checked}"
    assert not violations, "Latency checker reported violations:\n" + "\n".join(v.detail for v in violations)
    print(f"PASSED: latency checker measured {ops_checked} operation(s) with no violations")
