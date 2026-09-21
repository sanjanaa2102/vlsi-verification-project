"""Cycle-accurate, independent check that an accepted CTRL.START always
takes exactly OP_LATENCY cycles, using the DUT's verification-only
busy_o observability port (see apb_regblock.v).

Why this exists as its own mechanism, separate from the scoreboard: the
scoreboard's reference model is deliberately "software-realistic" --
it learns an operation finished only when the test polls STATUS and
observes BUSY=0, the same way real firmware would. That means a
transaction-level comparison alone cannot distinguish a correct
OP_LATENCY from an off-by-one defect that still completes somewhere
between two polls -- if the poll gap is coarser than the timing error,
the scoreboard would never see it. This checker watches busy_o every
single cycle and cannot miss that, independent of whatever polling
cadence any given test happens to use.
"""

from dataclasses import dataclass

import cocotb
from cocotb.triggers import RisingEdge


@dataclass
class LatencyViolation:
    detail: str


class ApbLatencyChecker:
    def __init__(self, dut, op_latency, hang_margin=100):
        self.dut = dut
        self.op_latency = op_latency
        self.hang_margin = hang_margin
        self.violations = []
        self.operations_checked = 0
        self._task = None

    def start(self):
        self._task = cocotb.start_soon(self._run())
        return self._task

    def stop(self):
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def result(self):
        return self.operations_checked, list(self.violations)

    async def _run(self):
        # Same reasoning as checker.py: don't read busy_o before the
        # first RisingEdge, since at true time 0 (before any reset
        # edge/clock edge) it can read 'X' and crash int().
        prev_busy = 0
        while True:
            await RisingEdge(self.dut.PCLK)
            if int(self.dut.PRESETn.value) == 0:
                prev_busy = 0
                continue
            busy = int(self.dut.busy_o.value)
            if not prev_busy and busy:
                cycles = await self._measure_operation()
                if cycles is not None:  # None means aborted by reset -- not a timing defect
                    self.operations_checked += 1
                    if cycles != self.op_latency:
                        self.violations.append(
                            LatencyViolation(f"operation took {cycles} cycles, expected exactly {self.op_latency}")
                        )
                busy = int(self.dut.busy_o.value)
            prev_busy = busy

    async def _measure_operation(self):
        """Called the cycle busy_o is first observed high (that edge
        counts as cycle 1). Bounded by construction -- a fixed number of
        further edges, not a "while busy" loop -- so this can never hang
        even against a stuck-busy-style mutant. Returns None if a reset
        interrupts the measurement (a deliberately-tested scenario, see
        test_apb_reset_mid_operation -- not a timing defect, the same
        way UART's checker excludes reset-aborted frames)."""
        cycles = 1
        for _ in range(self.op_latency + self.hang_margin):
            await RisingEdge(self.dut.PCLK)
            if int(self.dut.PRESETn.value) == 0:
                return None
            if int(self.dut.busy_o.value) == 0:
                # busy_o already dropped as of this edge -- it was NOT
                # high for this cycle, so don't count it.
                return cycles
            cycles += 1
        return cycles
