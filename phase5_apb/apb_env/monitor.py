"""Passively observes the apb_regblock DUT's APB bus and reconstructs
each completed transaction, independent of what the driver intended.

Since PREADY is tied high in this DUT, the ACCESS phase is always
exactly one cycle wide, so every rising edge where PSEL&&PENABLE are both
observed true corresponds to exactly one completed transfer -- unlike
UART's monitor, no multi-cycle frame-boundary detection is needed here.
"""

from dataclasses import dataclass

import cocotb
from cocotb.triggers import RisingEdge


@dataclass
class ApbTransaction:
    addr: int
    write: bool
    wdata: int
    rdata: int
    pslverr: bool


class ApbMonitor:
    def __init__(self, dut, callback):
        self.dut = dut
        self.callback = callback
        self._task = None

    def start(self):
        self._task = cocotb.start_soon(self._run())
        return self._task

    def stop(self):
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self):
        while True:
            await RisingEdge(self.dut.PCLK)
            if int(self.dut.PRESETn.value) == 0:
                continue
            if int(self.dut.PSEL.value) and int(self.dut.PENABLE.value):
                txn = ApbTransaction(
                    addr=int(self.dut.PADDR.value),
                    write=bool(int(self.dut.PWRITE.value)),
                    wdata=int(self.dut.PWDATA.value),
                    rdata=int(self.dut.PRDATA.value),
                    pslverr=bool(int(self.dut.PSLVERR.value)),
                )
                self.callback(txn)
