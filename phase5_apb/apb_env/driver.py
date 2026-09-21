"""Drives the apb_regblock DUT's APB input signals. Owns stimulus only --
same philosophy as phase1_uart's driver -- but blocking, unlike UART's:
an APB transfer is a short, deterministic request/response (SETUP then
ACCESS, one cycle each, PREADY tied high in this DUT), not an
open-ended async frame, so there is no reason to decouple issuing a
transfer from observing its result the way UART's send_byte() does.
"""

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge


class ApbDriver:
    def __init__(self, dut):
        self.dut = dut

    async def reset(self, hold_cycles=3):
        self.dut.PRESETn.value = 0
        self.dut.PSEL.value = 0
        self.dut.PENABLE.value = 0
        self.dut.PWRITE.value = 0
        self.dut.PADDR.value = 0
        self.dut.PWDATA.value = 0
        await ClockCycles(self.dut.PCLK, hold_cycles)
        self.dut.PRESETn.value = 1
        await RisingEdge(self.dut.PCLK)

    async def pulse_reset(self, hold_cycles=2):
        """Assert/deassert PRESETn without touching PSEL/PENABLE/PADDR --
        used to interrupt an in-flight transfer or operation."""
        self.dut.PRESETn.value = 0
        await ClockCycles(self.dut.PCLK, hold_cycles)
        self.dut.PRESETn.value = 1

    async def _transfer(self, addr, write, wdata=0, idle_cycles=0):
        if idle_cycles:
            await ClockCycles(self.dut.PCLK, idle_cycles)

        # SETUP phase
        self.dut.PADDR.value = addr
        self.dut.PWRITE.value = 1 if write else 0
        self.dut.PWDATA.value = wdata if write else 0
        self.dut.PSEL.value = 1
        self.dut.PENABLE.value = 0
        await RisingEdge(self.dut.PCLK)

        # ACCESS phase -- PREADY is tied high in this DUT, so the
        # transfer completes at the edge that ends this phase.
        self.dut.PENABLE.value = 1
        await RisingEdge(self.dut.PCLK)
        rdata = int(self.dut.PRDATA.value)
        err = bool(int(self.dut.PSLVERR.value))

        # Return to IDLE by default. If the caller issues another
        # transfer immediately (idle_cycles=0), PSEL is overwritten
        # before any clock edge observes it at 0, naturally producing a
        # correct back-to-back APB sequence (PSEL held, only PENABLE
        # toggles) -- the same idle_cycles=0 convention as UART's driver.
        self.dut.PSEL.value = 0
        self.dut.PENABLE.value = 0
        return rdata, err

    async def write(self, addr, data, idle_cycles=0):
        _, err = await self._transfer(addr, write=True, wdata=data, idle_cycles=idle_cycles)
        return err

    async def read(self, addr, idle_cycles=0):
        return await self._transfer(addr, write=False, idle_cycles=idle_cycles)

    async def wait_busy_clear(self, max_cycles=200, poll_gap=1):
        """Wait for the operation to finish using the busy_o
        observability port directly, NOT real APB STATUS reads.

        Deliberate: an earlier version of this polled STATUS over the
        real APB bus, but the monitor observes *every* bus transaction
        unconditionally and feeds it to the scoreboard -- since these
        polling reads were never registered as "expected" (registering
        them runs into the same predict-before-you-know-it ordering
        problem this method exists to avoid, see test_apb_regblock.py's
        _poll_until_idle docstring), they showed up as unmatched
        transactions and desynchronized the scoreboard's whole expected
        queue. Using busy_o for pure synchronization -- while leaving
        actual correctness checking to the scoreboard and
        ApbLatencyChecker, both fully black-box/cycle-accurate -- avoids
        that without weakening either check.

        Bounded, same reasoning as uart_env/driver.py's wait_idle: a
        broken DUT must fail this cleanly, not hang the regression.

        First waits for busy_o to actually rise. Confirmed by direct
        simulation (not assumed -- same class of race caught in
        uart_env/driver.py's send_byte): busy_o only becomes observable
        one cycle *after* the triggering CTRL write returns, not on the
        same cycle, so checking "while busy_o==1" immediately after
        issuing a start would see the still-0 value and return instantly
        without ever having waited for anything. Every call site of this
        method expects a real operation to be in flight (call sites where
        a start might have been legitimately ignored check BUSY directly
        instead), so waiting for the rise first is always correct here.
        """
        cycles = 0
        while int(self.dut.busy_o.value) == 0:
            await ClockCycles(self.dut.PCLK, 1)
            cycles += 1
            if cycles > max_cycles:
                raise AssertionError(f"busy_o did not rise within {max_cycles} cycles of a start")

        cycles = 0
        while int(self.dut.busy_o.value) == 1:
            await ClockCycles(self.dut.PCLK, poll_gap)
            cycles += poll_gap
            if cycles > max_cycles:
                raise AssertionError(f"busy_o did not clear within {max_cycles} cycles")

        # Settle margin: ApbLatencyChecker watches busy_o independently
        # and needs a couple of cycles, after this same clear event, to
        # finish its own measurement and record it -- confirmed by direct
        # testing that returning immediately here can race ahead of that
        # (both are separate tasks polling the same signal; nothing
        # guarantees which one's continuation the scheduler runs first
        # on the edge busy_o drops). Without this, operations could
        # silently go unmeasured rather than fail loudly.
        await ClockCycles(self.dut.PCLK, 3)
