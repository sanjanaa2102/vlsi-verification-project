"""Directed regression for apb_regblock, built on the apb_env driver /
monitor / scoreboard / checker architecture (see apb_env/ and
VERIFICATION_PLAN.md).

This module is what mutation_suite.py's "scoreboard" mechanism targets.
"""

import cocotb

from apb_env import ADDR_CTRL, ADDR_DATA, ADDR_INTCLR, ADDR_STATUS, coverage, finish, setup


async def _poll_until_idle(driver):
    """Wait for BUSY to clear using the driver's own unchecked polling
    utility (NOT scoreboard-checked per poll). This is deliberate: the
    reference model can only predict a status read correctly if it has
    already been told the operation completed, but the model only finds
    that out by comparing against the real DUT -- checking every poll
    would create a circular ordering problem (an early mismatch is not a
    bug, it's the model being asked to predict something it cannot yet
    know). Callers tell the model the operation is done via
    scoreboard.complete_pending_operation() once this returns, then issue
    one freshly-checked STATUS read to confirm the final state."""
    await driver.wait_busy_clear()


async def _access(driver, scoreboard, addr, write, data=0):
    """Issue one transaction, pre-registering the expectation with the
    scoreboard and sampling reg-access coverage. Returns (rdata, err)."""
    coverage.sample_access(addr, "write" if write else "read")
    if write:
        scoreboard.expect_write(addr, data)
        err = await driver.write(addr, data)
        return None, err
    scoreboard.expect_read(addr)
    rdata, err = await driver.read(addr)
    return rdata, err


@cocotb.test()
async def test_apb_reset_state(dut):
    """Feature: after reset, CTRL/STATUS/DATA all read as zero.
    Check: scoreboard against the reference model's post-reset state."""
    driver, scoreboard, monitor, checker, latency_checker = await setup(dut)

    for addr in (ADDR_CTRL, ADDR_STATUS, ADDR_DATA):
        rdata, err = await _access(driver, scoreboard, addr, write=False)
        assert not err
        assert rdata == 0x00, f"addr {addr:#04x}: expected 0x00 after reset, got {rdata:#04x}"

    checked = await finish(driver, scoreboard, monitor, checker, latency_checker)
    assert checked == 3
    print("PASSED: all registers read 0 after reset")


@cocotb.test()
async def test_apb_data_rw(dut):
    """Feature: DATA is a plain read/write register.
    Check: scoreboard compares monitor-observed PRDATA against the
    reference model for a range of values."""
    driver, scoreboard, monitor, checker, latency_checker = await setup(dut)

    for val in (0x00, 0xFF, 0xA5, 0x5A, 0x01, 0x80):
        _, err = await _access(driver, scoreboard, ADDR_DATA, write=True, data=val)
        assert not err
        rdata, err = await _access(driver, scoreboard, ADDR_DATA, write=False)
        assert not err
        assert rdata == val, f"expected {val:#04x}, got {rdata:#04x}"

    checked = await finish(driver, scoreboard, monitor, checker, latency_checker)
    assert checked == 12
    print("PASSED: DATA read/write round-trips correctly for all values")


@cocotb.test()
async def test_apb_reserved_bits_masked(dut):
    """Feature: CTRL bits[7:2] are reserved and must always read 0,
    regardless of what was written (and START, bit1, always reads 0 --
    it is a pulse, not a stored bit).
    Check: scoreboard, via the reference model's ctrl_read()."""
    driver, scoreboard, monitor, checker, latency_checker = await setup(dut)

    _, err = await _access(driver, scoreboard, ADDR_CTRL, write=True, data=0xFF)
    assert not err
    rdata, err = await _access(driver, scoreboard, ADDR_CTRL, write=False)
    assert not err
    assert rdata == 0x01, f"expected only bit0 (ENABLE) set, got {rdata:#04x}"

    checked = await finish(driver, scoreboard, monitor, checker, latency_checker)
    assert checked == 2
    print("PASSED: reserved CTRL bits and START read back as 0")


@cocotb.test()
async def test_apb_operation_accepted(dut):
    """Feature: with ENABLE already set from a prior write, a separate
    CTRL write with START=1 triggers the operation; after it completes,
    DATA increments by one and DONE is set.
    Check: scoreboard on every transaction, including the polling reads;
    OP_LATENCY correctness is independently verified by the latency
    checker (attached via the harness), not asserted here."""
    driver, scoreboard, monitor, checker, latency_checker = await setup(dut)

    _, err = await _access(driver, scoreboard, ADDR_DATA, write=True, data=0x10)
    assert not err
    _, err = await _access(driver, scoreboard, ADDR_CTRL, write=True, data=0x01)  # ENABLE only
    assert not err
    _, err = await _access(driver, scoreboard, ADDR_CTRL, write=True, data=0x02)  # START only
    assert not err

    await _poll_until_idle(driver)
    scoreboard.complete_pending_operation()
    rdata, err = await _access(driver, scoreboard, ADDR_STATUS, write=False)
    assert not err
    assert rdata & 0x02, "DONE should be set after the operation completes"

    rdata, err = await _access(driver, scoreboard, ADDR_DATA, write=False)
    assert not err
    assert rdata == 0x11, f"expected DATA incremented to 0x11, got {rdata:#04x}"

    ops_checked, _ = latency_checker.result()
    assert ops_checked == 1, f"expected the latency checker to have measured 1 operation, got {ops_checked}"

    checked = await finish(driver, scoreboard, monitor, checker, latency_checker)
    print(f"PASSED: operation accepted and completed correctly ({checked} transactions checked)")


@cocotb.test()
async def test_apb_start_same_write_is_noop(dut):
    """Feature: writing ENABLE and START together in the *same* CTRL
    write does not start an operation -- START's condition checks the
    already-committed ENABLE value, not the bit just written in this
    access (see apb_regblock.v). Check: scoreboard + a direct BUSY check.
    Coverage: samples top.start_control = 'start_while_disabled' (from
    this DUT's point of view, ENABLE was still 0 at the moment START was
    evaluated)."""
    driver, scoreboard, monitor, checker, latency_checker = await setup(dut)

    coverage.sample_start_control("start_while_disabled")
    _, err = await _access(driver, scoreboard, ADDR_CTRL, write=True, data=0x03)  # ENABLE+START together
    assert not err

    rdata, err = await _access(driver, scoreboard, ADDR_STATUS, write=False)
    assert not err
    assert not (rdata & 0x01), "BUSY should NOT be set -- START and ENABLE were written in the same access"

    checked = await finish(driver, scoreboard, monitor, checker, latency_checker)
    assert checked == 2
    print("PASSED: ENABLE+START in one write does not start an operation")


@cocotb.test()
async def test_apb_start_while_disabled_is_noop(dut):
    """Feature: START is ignored while ENABLE has never been set.
    Coverage: top.start_control = 'start_while_disabled'."""
    driver, scoreboard, monitor, checker, latency_checker = await setup(dut)

    coverage.sample_start_control("start_while_disabled")
    _, err = await _access(driver, scoreboard, ADDR_CTRL, write=True, data=0x02)  # START only, never enabled
    assert not err

    rdata, err = await _access(driver, scoreboard, ADDR_STATUS, write=False)
    assert not err
    assert not (rdata & 0x01), "BUSY should NOT be set -- ENABLE was never set"

    checked = await finish(driver, scoreboard, monitor, checker, latency_checker)
    assert checked == 2
    print("PASSED: START while disabled is ignored")


@cocotb.test()
async def test_apb_start_while_busy_is_ignored(dut):
    """Feature: a second START while an operation is already in flight
    does not retrigger/extend it. Coverage: top.start_control =
    'start_while_busy'.

    The retrigger write re-asserts ENABLE immediately before re-asserting
    START (rather than writing START alone a second time). This is
    deliberate, not redundant: every CTRL write unconditionally updates
    enable_reg <= PWDATA[0], so the *first* START-only write (data=0x02)
    already clears enable_reg as a side effect; a second START-only write
    would then fail to retrigger regardless of whether the busy guard is
    even present, making the busy guard itself untested. Confirmed by
    direct simulation against a mutant with the guard removed: without
    the extra ENABLE-reassert write, this test could not distinguish
    correct RTL from a missing busy guard at all. See
    VERIFICATION_PLAN.md."""
    driver, scoreboard, monitor, checker, latency_checker = await setup(dut)

    _, err = await _access(driver, scoreboard, ADDR_CTRL, write=True, data=0x01)  # ENABLE
    assert not err
    _, err = await _access(driver, scoreboard, ADDR_CTRL, write=True, data=0x02)  # START -> accepted
    assert not err

    _, err = await _access(driver, scoreboard, ADDR_CTRL, write=True, data=0x01)  # re-assert ENABLE while busy
    assert not err
    coverage.sample_start_control("start_while_busy")
    _, err = await _access(driver, scoreboard, ADDR_CTRL, write=True, data=0x02)  # retrigger attempt, while busy
    assert not err

    await _poll_until_idle(driver)
    scoreboard.complete_pending_operation()

    rdata, err = await _access(driver, scoreboard, ADDR_DATA, write=False)
    assert not err
    assert rdata == 0x01, f"operation should have run exactly once, expected DATA=0x01, got {rdata:#04x}"

    ops_checked, _ = latency_checker.result()
    assert ops_checked == 1, f"expected exactly 1 measured operation (the ignored retrigger must not count), got {ops_checked}"

    checked = await finish(driver, scoreboard, monitor, checker, latency_checker)
    print(f"PASSED: START while busy did not retrigger the operation ({checked} transactions checked)")


@cocotb.test()
async def test_apb_intclr(dut):
    """Feature: INTCLR (bit1=1) clears DONE when it was set, and is a
    no-op when DONE was already 0. Coverage: top.intclr_effect (both
    bins)."""
    driver, scoreboard, monitor, checker, latency_checker = await setup(dut)

    coverage.sample_intclr("noop")
    _, err = await _access(driver, scoreboard, ADDR_INTCLR, write=True, data=0x02)  # DONE already 0
    assert not err
    rdata, err = await _access(driver, scoreboard, ADDR_STATUS, write=False)
    assert not err
    assert not (rdata & 0x02)

    _, err = await _access(driver, scoreboard, ADDR_CTRL, write=True, data=0x01)  # ENABLE
    assert not err
    _, err = await _access(driver, scoreboard, ADDR_CTRL, write=True, data=0x02)  # START
    assert not err
    await _poll_until_idle(driver)
    scoreboard.complete_pending_operation()

    rdata, err = await _access(driver, scoreboard, ADDR_STATUS, write=False)
    assert not err
    assert rdata & 0x02, "DONE should be set after the operation"

    coverage.sample_intclr("cleared_done")
    _, err = await _access(driver, scoreboard, ADDR_INTCLR, write=True, data=0x02)
    assert not err
    rdata, err = await _access(driver, scoreboard, ADDR_STATUS, write=False)
    assert not err
    assert not (rdata & 0x02), "DONE should be cleared after INTCLR"

    ops_checked, _ = latency_checker.result()
    assert ops_checked == 1, f"expected 1 measured operation, got {ops_checked}"

    checked = await finish(driver, scoreboard, monitor, checker, latency_checker)
    print(f"PASSED: INTCLR clears DONE when set and is a no-op when not ({checked} transactions checked)")


@cocotb.test()
async def test_apb_illegal_accesses(dut):
    """Feature: an illegal write (to STATUS, or an out-of-range address)
    and an illegal read (from INTCLR, or an out-of-range address) are
    both flagged via PSLVERR, and do not corrupt any register state.
    Check: scoreboard, via reference_model.is_illegal_write/read."""
    driver, scoreboard, monitor, checker, latency_checker = await setup(dut)

    _, err = await _access(driver, scoreboard, ADDR_STATUS, write=True, data=0xFF)
    assert err, "write to STATUS (read-only) should raise PSLVERR"

    _, err = await _access(driver, scoreboard, 0x14, write=True, data=0xFF)
    assert err, "write to an out-of-range address should raise PSLVERR"

    rdata, err = await _access(driver, scoreboard, ADDR_INTCLR, write=False)
    assert err, "read from INTCLR (write-only) should raise PSLVERR"

    rdata, err = await _access(driver, scoreboard, 0x14, write=False)
    assert err, "read from an out-of-range address should raise PSLVERR"

    rdata, err = await _access(driver, scoreboard, ADDR_DATA, write=False)
    assert not err
    assert rdata == 0x00, "DATA must be unaffected by the preceding illegal accesses"

    checked = await finish(driver, scoreboard, monitor, checker, latency_checker)
    assert checked == 5
    print("PASSED: illegal writes/reads flagged via PSLVERR without corrupting state")


@cocotb.test()
async def test_apb_reset_mid_operation(dut):
    """Feature: PRESETn asserted while an operation is in flight safely
    aborts it -- ENABLE/DATA/BUSY/DONE all return to their reset values,
    and the DUT works correctly afterward.
    Check: direct post-reset register reads (scoreboard, against a fresh
    reference model), plus a normal operation afterward to confirm
    recovery."""
    driver, scoreboard, monitor, checker, latency_checker = await setup(dut)

    _, err = await _access(driver, scoreboard, ADDR_DATA, write=True, data=0x42)
    assert not err
    _, err = await _access(driver, scoreboard, ADDR_CTRL, write=True, data=0x01)
    assert not err
    _, err = await _access(driver, scoreboard, ADDR_CTRL, write=True, data=0x02)
    assert not err

    await driver.pulse_reset(hold_cycles=2)
    scoreboard.model.reset()  # DUT is fully reset -- reference model follows

    for addr in (ADDR_CTRL, ADDR_STATUS, ADDR_DATA):
        rdata, err = await _access(driver, scoreboard, addr, write=False)
        assert not err
        assert rdata == 0x00, f"addr {addr:#04x}: expected 0x00 after mid-operation reset, got {rdata:#04x}"

    # DUT must still work correctly afterward.
    _, err = await _access(driver, scoreboard, ADDR_CTRL, write=True, data=0x01)
    assert not err
    _, err = await _access(driver, scoreboard, ADDR_CTRL, write=True, data=0x02)
    assert not err
    await _poll_until_idle(driver)
    scoreboard.complete_pending_operation()
    rdata, err = await _access(driver, scoreboard, ADDR_DATA, write=False)
    assert not err
    assert rdata == 0x01

    ops_checked, _ = latency_checker.result()
    assert ops_checked == 1, (
        f"expected exactly 1 measured operation (the reset-aborted one must not "
        f"count as a timing defect), got {ops_checked}"
    )

    checked = await finish(driver, scoreboard, monitor, checker, latency_checker)
    print(f"PASSED: DUT recovered from a mid-operation reset and worked correctly afterward ({checked} checked)")
