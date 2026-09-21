"""Drives the uart_tx DUT's input pins. Owns stimulus only -- it has no
notion of "correct" and performs no checking; that is the scoreboard's job.
"""

import cocotb
from cocotb.triggers import ClockCycles

from .reference_model import CLKS_PER_BIT_DEFAULT


def resolve_clks_per_bit(dut):
    """Read CLKS_PER_BIT from the DUT hierarchy when the simulator exposes
    it, falling back to the known default otherwise (Icarus VPI does not
    always surface Verilog `parameter`s as readable objects)."""
    if hasattr(dut, "CLKS_PER_BIT"):
        try:
            return int(dut.CLKS_PER_BIT.value)
        except (TypeError, ValueError):
            pass
    return CLKS_PER_BIT_DEFAULT


class UartTxDriver:
    def __init__(self, dut, clks_per_bit=None):
        self.dut = dut
        self.clks_per_bit = clks_per_bit or resolve_clks_per_bit(dut)

    async def reset(self, hold_cycles=3):
        self.dut.rst.value = 1
        self.dut.tx_start.value = 0
        self.dut.tx_data.value = 0
        await ClockCycles(self.dut.clk, hold_cycles)
        self.dut.rst.value = 0
        await ClockCycles(self.dut.clk, 1)

    async def pulse_reset(self, hold_cycles=2):
        """Assert/deassert reset without touching tx_start/tx_data -- used
        to interrupt an in-flight frame."""
        self.dut.rst.value = 1
        await ClockCycles(self.dut.clk, hold_cycles)
        self.dut.rst.value = 0

    async def wait_idle(self, max_cycles=200):
        """Poll tx_busy until it deasserts. Bounded so a broken DUT (e.g.
        busy stuck high) fails the test cleanly and quickly instead of
        hanging the whole regression -- max_cycles is set well above the
        longest legitimate frame (10 segments * CLKS_PER_BIT)."""
        cycles = 0
        while int(self.dut.tx_busy.value) == 1:
            await ClockCycles(self.dut.clk, 1)
            cycles += 1
            if cycles > max_cycles:
                raise AssertionError(
                    f"tx_busy did not deassert within {max_cycles} cycles"
                )

    async def send_byte(self, byte_val, idle_cycles=0):
        """Start transmission of one byte.

        idle_cycles=0 issues tx_start on the very first cycle the bus is
        idle (back-to-back framing); idle_cycles>0 leaves the bus idle for
        that many extra cycles first (gapped framing). Does not block for
        the frame to finish -- the monitor observes completion
        independently.
        """
        await self.wait_idle()
        if idle_cycles:
            await ClockCycles(self.dut.clk, idle_cycles)
        self.dut.tx_data.value = byte_val
        self.dut.tx_start.value = 1
        await ClockCycles(self.dut.clk, 1)
        self.dut.tx_start.value = 0
        # tx_busy becomes externally visible one cycle after the start pulse
        # is sampled, not on the same cycle send_byte() issues it. Wait for
        # it here so callers can safely call wait_idle() immediately after
        # send_byte() returns without racing past a still-idle-looking bus.
        #
        # Bounded for the same reason as wait_idle(): found by mutation
        # testing (mutant7_incomplete_reset) that a DUT whose FSM can drift
        # away from IDLE without going through it again (e.g. a broken
        # reset) will never legitimately re-raise tx_busy in response to a
        # new tx_start, since only the IDLE state's case branch checks
        # tx_start at all -- an unbounded wait here hung the whole
        # regression instead of failing the test.
        cycles = 0
        while int(self.dut.tx_busy.value) == 0:
            await ClockCycles(self.dut.clk, 1)
            cycles += 1
            if cycles > 200:
                raise AssertionError(
                    "tx_busy did not rise within 200 cycles of a start pulse "
                    "-- DUT may not be responding to tx_start"
                )
