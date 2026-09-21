"""Protocol/timing invariant checker for uart_tx -- independent of the
scoreboard.

Why this exists as a separate mechanism, and why it looks like this:

Icarus Verilog 12.0 was verified (not assumed) to have no support for
concurrent/temporal SystemVerilog assertions: `property`, `assert
property`, `##`, and `|->` sequences all fail to parse. Simple *immediate*
assertions (`assert (expr) else ...`) do compile, but the invariants that
matter for this protocol -- "this segment must hold a constant value for
exactly CLKS_PER_BIT cycles", "a frame must take exactly 10*CLKS_PER_BIT
cycles" -- are inherently temporal. Expressing them as immediate
assertions would mean re-implementing cycle-by-cycle history tracking
inside a Verilog always-block, at which point there is no real benefit
over doing it in Python. The strongest mechanism actually available in
this free, no-billing toolchain is therefore a cocotb concurrent checker.

What makes this categorically different from UartTxScoreboard: the
scoreboard knows what byte the driver asked for and compares the decoded
result against it (a *data-value* check). This checker is never told what
byte was sent -- every invariant here is a structural/timing rule from the
UART 8N1 protocol itself, true for *any* byte value:

  1. idle level:      tx_busy==0  => tx_serial==1
  2. frame duration:  every frame's tx_busy-high period is exactly
                       10 * CLKS_PER_BIT cycles
  3. start-bit:        the first segment of every frame is constant 0
  4. stop-bit:          the last segment of every frame is constant 1
  5. data-bit steadiness: each of the middle 8 segments is constant for
                       its full CLKS_PER_BIT cycles (whatever the value)

Because these checks never consult expected data, a mutant that only
corrupts *which* bits are sent (not the frame's timing/framing) -- e.g. a
bit-order bug -- is invisible to this checker and only catchable by the
scoreboard. See VERIFICATION_PLAN.md for the measured breakdown.
"""

from dataclasses import dataclass, field

import cocotb
from cocotb.triggers import RisingEdge


@dataclass
class Violation:
    frame_index: int
    rule: str
    detail: str


class UartTxProtocolChecker:
    def __init__(self, dut, clks_per_bit):
        self.dut = dut
        self.clks_per_bit = clks_per_bit
        self.violations = []
        self.frames_checked = 0
        self._task = None

    def start(self):
        self._task = cocotb.start_soon(self._run())
        return self._task

    def stop(self):
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def result(self):
        return self.frames_checked, list(self.violations)

    async def _run(self):
        prev_busy = int(self.dut.tx_busy.value)
        while True:
            await RisingEdge(self.dut.clk)
            if int(self.dut.rst.value) == 1:
                prev_busy = int(self.dut.tx_busy.value)
                continue

            busy = int(self.dut.tx_busy.value)

            if not busy and int(self.dut.tx_serial.value) != 1:
                self.violations.append(
                    Violation(
                        self.frames_checked,
                        "idle_level",
                        "tx_serial != 1 while tx_busy == 0",
                    )
                )

            if not prev_busy and busy:
                await self._check_frame()
                busy = int(self.dut.tx_busy.value)

            prev_busy = busy

    async def _check_frame(self):
        """Called on the edge tx_busy is first observed high.

        Verified against golden RTL by direct instrumented simulation (not
        assumed): this triggering edge is itself a busy-high cycle where
        tx_serial is still at the idle level -- the real 10-segment frame
        content begins on the *next* edge and spans exactly
        10*CLKS_PER_BIT further edges, with tx_busy deasserting on the
        same edge as the last sample of segment 9 (the stop bit). So:
        start busy_cycles at 1 (for this triggering edge), then collect
        exactly 10*CLKS_PER_BIT more tx_serial samples while counting how
        many of those edges also had tx_busy==1 (39 of 40 for a correct
        frame). The sample count is a fixed size, not a "while busy"
        condition, so this can never hang even if a mutant makes tx_busy
        stick high.
        """
        busy_cycles = 1
        serial_samples = []
        needed = 10 * self.clks_per_bit
        aborted = False

        while len(serial_samples) < needed:
            await RisingEdge(self.dut.clk)
            if int(self.dut.rst.value) == 1:
                aborted = True
                break
            if int(self.dut.tx_busy.value) == 1:
                busy_cycles += 1
            serial_samples.append(int(self.dut.tx_serial.value))

        self.frames_checked += 1

        if aborted:
            # A reset mid-frame is a deliberate, separately-tested scenario
            # (see test_uart_tx_reset_mid_frame) -- not a protocol
            # violation by itself.
            return

        segments = [
            serial_samples[i * self.clks_per_bit : (i + 1) * self.clks_per_bit] for i in range(10)
        ]

        # Rule 3: start bit is constant 0.
        if not all(s == 0 for s in segments[0]):
            self.violations.append(
                Violation(self.frames_checked, "start_bit", f"expected constant 0, got {segments[0]}")
            )

        # Rule 5: each data segment is internally constant (value itself is
        # not checked here -- that is data content, the scoreboard's job).
        for i, seg in enumerate(segments[1:9], start=1):
            if not all(s == seg[0] for s in seg):
                self.violations.append(
                    Violation(self.frames_checked, "data_bit_steadiness", f"segment {i} not constant: {seg}")
                )

        # Rule 4: stop bit is constant 1.
        if not all(s == 1 for s in segments[9]):
            self.violations.append(
                Violation(self.frames_checked, "stop_bit", f"expected constant 1, got {segments[9]}")
            )

        # Rule 2: total busy-high duration is exactly 10 * CLKS_PER_BIT.
        expected_cycles = 10 * self.clks_per_bit
        if busy_cycles != expected_cycles:
            self.violations.append(
                Violation(
                    self.frames_checked,
                    "frame_duration",
                    f"expected tx_busy high for exactly {expected_cycles} cycles, "
                    f"observed {busy_cycles}",
                )
            )
