"""Passively observes the uart_tx DUT's outputs and reconstructs frames.

The monitor has no knowledge of what the driver intended to send. It
detects a frame by watching tx_busy transition low->high (the same cycle
the DUT's own IDLE state machine branch commits busy_reg<=1), then samples
tx_serial cycle-by-cycle for CLKS_PER_BIT cycles per segment across all 10
segments (start, 8 data bits LSB-first, stop). This independently verifies
bit timing -- it never assumes a bit boundary from a fixed time offset.
"""

from dataclasses import dataclass, field

import cocotb
from cocotb.triggers import RisingEdge


@dataclass
class Transaction:
    byte_val: int | None
    segment_samples: list = field(default_factory=list)
    aborted: bool = False
    busy_ok: bool = True


class UartTxMonitor:
    def __init__(self, dut, clks_per_bit, callback):
        self.dut = dut
        self.clks_per_bit = clks_per_bit
        self.callback = callback
        self._task = None

    def start(self):
        self._task = cocotb.start_soon(self._run())
        return self._task

    def stop(self):
        """Kill the background sampling task. cocotb does not reset
        simulation state between @cocotb.test() functions in the same
        module, so a monitor left running would keep consuming events
        (and driving stale callbacks) into the next test."""
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self):
        prev_busy = int(self.dut.tx_busy.value)
        while True:
            await RisingEdge(self.dut.clk)
            busy = int(self.dut.tx_busy.value)
            if not prev_busy and busy:
                txn = await self._sample_frame()
                self.callback(txn)
                busy = int(self.dut.tx_busy.value)
            prev_busy = busy

    async def _sample_frame(self):
        segments = []
        aborted = False
        for _seg_idx in range(10):
            samples = []
            for _cycle in range(self.clks_per_bit):
                await RisingEdge(self.dut.clk)
                if int(self.dut.rst.value) == 1:
                    aborted = True
                    break
                samples.append(int(self.dut.tx_serial.value))
            if aborted:
                break
            segments.append(samples)

        if aborted:
            return Transaction(byte_val=None, segment_samples=segments, aborted=True)

        data_bits = [seg[0] for seg in segments[1:9]]
        byte_val = sum(b << i for i, b in enumerate(data_bits))

        await RisingEdge(self.dut.clk)
        busy_ok = int(self.dut.tx_busy.value) == 0

        return Transaction(
            byte_val=byte_val, segment_samples=segments, aborted=False, busy_ok=busy_ok
        )
