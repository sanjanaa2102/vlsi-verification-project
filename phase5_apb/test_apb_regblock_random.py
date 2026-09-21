"""Phase 5 constrained-random regression for apb_regblock.

Reproducing a failure: cocotb seeds and logs Python's global `random`
module every run ("Seeding Python random module with <seed>");
apb_env.sequences builds on that same module, so a failure reproduces
with `make MODULE=test_apb_regblock_random COCOTB_RANDOM_SEED=<seed>`.
Every scenario is logged by name and index as it runs.

Unlike UART, the interesting randomness here is less about one
transaction's data and more about which control-flow scenario runs and
in what order -- so every scenario/coverage-bin class is *guaranteed*
(deterministic, not left to chance) to run exactly the combinations
needed for 100% closure on all 5 CoverPoints/cross regardless of seed;
only the order, and the random data/idle-gap values within each
scenario, are randomized. (An earlier version of this file picked
illegal-access targets with a 50/50 coin flip inside the scenario --
that made coverage closure seed-flaky, since e.g. an "illegal write to
STATUS" cell could go unhit on an unlucky seed; fixed by making every
required cross-cell an explicit, deterministic scenario.)
"""

import random

import cocotb

from apb_env import ADDR_CTRL, ADDR_DATA, ADDR_INTCLR, ADDR_STATUS, coverage, finish, setup
from apb_env.sequences import random_data, random_idle_cycles, random_invalid_addr


async def _access(driver, scoreboard, addr, write, data=0, idle_cycles=0):
    coverage.sample_access(addr, "write" if write else "read")
    if write:
        scoreboard.expect_write(addr, data)
        err = await driver.write(addr, data, idle_cycles=idle_cycles)
        return None, err
    scoreboard.expect_read(addr)
    rdata, err = await driver.read(addr, idle_cycles=idle_cycles)
    return rdata, err


# -- Guaranteed scenarios: each closes one or more specific coverage
# cells deterministically. Random data/idle values still vary run to run.


async def _scenario_data_rw(driver, scoreboard):
    val = random_data()
    await _access(driver, scoreboard, ADDR_DATA, write=True, data=val, idle_cycles=random_idle_cycles())
    rdata, err = await _access(driver, scoreboard, ADDR_DATA, write=False, idle_cycles=random_idle_cycles())
    assert not err
    assert rdata == val


async def _scenario_read_ctrl(driver, scoreboard):
    rdata, err = await _access(driver, scoreboard, ADDR_CTRL, write=False, idle_cycles=random_idle_cycles())
    assert not err


async def _scenario_illegal_write_status(driver, scoreboard):
    _, err = await _access(
        driver, scoreboard, ADDR_STATUS, write=True, data=random_data(), idle_cycles=random_idle_cycles()
    )
    assert err


async def _scenario_illegal_write_invalid(driver, scoreboard):
    _, err = await _access(
        driver, scoreboard, random_invalid_addr(), write=True, data=random_data(), idle_cycles=random_idle_cycles()
    )
    assert err


async def _scenario_illegal_read_intclr(driver, scoreboard):
    _, err = await _access(driver, scoreboard, ADDR_INTCLR, write=False, idle_cycles=random_idle_cycles())
    assert err


async def _scenario_illegal_read_invalid(driver, scoreboard):
    _, err = await _access(driver, scoreboard, random_invalid_addr(), write=False, idle_cycles=random_idle_cycles())
    assert err


async def _scenario_start_while_disabled(driver, scoreboard):
    coverage.sample_start_control("start_while_disabled")
    await _access(driver, scoreboard, ADDR_CTRL, write=True, data=0x02, idle_cycles=random_idle_cycles())
    rdata, err = await _access(driver, scoreboard, ADDR_STATUS, write=False)
    assert not err
    assert not (rdata & 0x01)


async def _scenario_operation_leave_done_set(driver, scoreboard):
    """ENABLE, START (two writes -- see apb_regblock.v for why they must
    be separate), wait for completion, deliberately leave DONE set."""
    await _access(driver, scoreboard, ADDR_CTRL, write=True, data=0x01, idle_cycles=random_idle_cycles())
    coverage.sample_start_control("start_accepted")
    await _access(driver, scoreboard, ADDR_CTRL, write=True, data=0x02, idle_cycles=random_idle_cycles())
    await driver.wait_busy_clear()
    scoreboard.complete_pending_operation()


async def _scenario_start_while_busy(driver, scoreboard):
    """The retrigger write re-asserts ENABLE immediately before
    re-asserting START, with no idle gap anywhere in this sequence --
    deliberate, not incidental. Every CTRL write unconditionally updates
    enable_reg, so a bare second START-only write would already fail to
    retrigger regardless of whether the busy guard exists (it clears its
    own enable bit); and any idle gap risks the retrigger landing after
    the operation has already naturally completed, silently degrading
    this into "start after busy", not "start while busy". Both failure
    modes were found empirically (see test_apb_regblock.py's
    test_apb_start_while_busy_is_ignored docstring) to make this scenario
    unable to distinguish correct RTL from a missing busy guard at all."""
    await _access(driver, scoreboard, ADDR_CTRL, write=True, data=0x01, idle_cycles=0)
    coverage.sample_start_control("start_accepted")
    await _access(driver, scoreboard, ADDR_CTRL, write=True, data=0x02, idle_cycles=0)
    await _access(driver, scoreboard, ADDR_CTRL, write=True, data=0x01, idle_cycles=0)
    coverage.sample_start_control("start_while_busy")
    await _access(driver, scoreboard, ADDR_CTRL, write=True, data=0x02, idle_cycles=0)
    await driver.wait_busy_clear()
    scoreboard.complete_pending_operation()

    expected_data = scoreboard.model.data
    rdata, err = await _access(driver, scoreboard, ADDR_DATA, write=False, idle_cycles=random_idle_cycles())
    assert not err
    assert rdata == expected_data, (
        f"operation should have run exactly once (the retrigger while busy must be ignored), "
        f"expected DATA={expected_data:#04x}, got {rdata:#04x}"
    )

    # DONE is guaranteed 1 here (an operation just completed) -- a
    # truthful, deterministic 'cleared_done' case.
    coverage.sample_intclr("cleared_done")
    await _access(driver, scoreboard, ADDR_INTCLR, write=True, data=0x02, idle_cycles=random_idle_cycles())


GUARANTEED_SCENARIOS = [
    _scenario_data_rw,
    _scenario_read_ctrl,
    _scenario_illegal_write_status,
    _scenario_illegal_write_invalid,
    _scenario_illegal_read_intclr,
    _scenario_illegal_read_invalid,
    _scenario_start_while_disabled,
    _scenario_operation_leave_done_set,
    _scenario_start_while_busy,
]

# Extra randomized repeats on top of the guaranteed set -- more
# exploration, not needed for coverage closure.
FILLER_SCENARIOS = [_scenario_data_rw, _scenario_illegal_write_invalid, _scenario_illegal_read_invalid]


@cocotb.test()
async def test_apb_random_sweep(dut):
    """Feature: a randomized mix of legal/illegal accesses and control
    scenarios all behave correctly. See module docstring for the
    guarantee-vs-randomize split."""
    driver, scoreboard, monitor, checker, latency_checker = await setup(dut)

    # DONE is guaranteed 0 here (right after reset, before any operation
    # has ever run) -- a truthful, deterministic 'noop' INTCLR case.
    assert not scoreboard.model.done
    coverage.sample_intclr("noop")
    await _access(driver, scoreboard, ADDR_INTCLR, write=True, data=0x02, idle_cycles=random_idle_cycles())

    order = list(GUARANTEED_SCENARIOS) + [random.choice(FILLER_SCENARIOS) for _ in range(5)]
    random.shuffle(order)

    for i, scenario in enumerate(order):
        cocotb.log.info(f"scenario[{i}]: {scenario.__name__}")
        await scenario(driver, scoreboard)

    checked = await finish(driver, scoreboard, monitor, checker, latency_checker)
    print(f"PASSED: {checked} transactions across {len(order) + 1} randomized scenarios")


@cocotb.test()
async def test_apb_random_coverage_report(dut):
    """Not a functional check -- runs last in this module, reports and
    exports the coverage accumulated by test_apb_random_sweep. This
    module is the sole owner of all 5 CoverPoints/cross (apb_regblock has
    one coverage.py, unlike UART's Phase-2/Phase-3 split)."""
    coverage.report(cocotb.log.info)
    coverage.export("sim_build/coverage_random.yml")

    owned = [
        "top.reg_class",
        "top.direction",
        "top.reg_class_x_direction",
        "top.start_control",
        "top.intclr_effect",
    ]
    for name in owned:
        pct = coverage.bin_percentage(name)
        cocotb.log.info(f"{name}: {pct:.1f}%")
        assert pct == 100.0, f"expected 100% coverage on {name}, got {pct:.1f}%"

    cocotb.log.info(f"Overall functional coverage: {coverage.overall_percentage():.1f}%")
