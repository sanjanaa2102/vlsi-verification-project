"""APB bus interface protocol checker -- pure interface timing/sequencing
invariants that would apply to *any* APB4 slave, deliberately independent
of this DUT's register map. Register-map legality and PSLVERR
correctness are a device-specific concern handled by the scoreboard
(scoreboard.py), not here -- see VERIFICATION_PLAN.md for why mixing the
two would misrepresent an implementation-specific policy as an APB
protocol rule.

Checked, independent of the scoreboard:
  1. PENABLE is never asserted while PSEL is low.
  2. SETUP (PSEL & !PENABLE) is followed immediately by ACCESS
     (PSEL & PENABLE) the very next cycle -- SETUP is always exactly one
     cycle, never held or abandoned.
  3. PADDR/PWRITE/PWDATA are stable from SETUP into ACCESS.
  4. PREADY is asserted during ACCESS (this DUT is a zero-wait-state
     slave, so completion must be signalled on the very cycle access
     happens).

As with the UART checker, this is a cocotb concurrent checker, not SVA --
same verified toolchain limitation (Icarus Verilog 12.0 has no
concurrent/temporal SVA support), same reasoning as uart_env/checker.py.
"""

from dataclasses import dataclass

import cocotb
from cocotb.triggers import RisingEdge


@dataclass
class Violation:
    cycle: int
    rule: str
    detail: str


class ApbProtocolChecker:
    def __init__(self, dut):
        self.dut = dut
        self.violations = []
        self.cycles_checked = 0
        self._task = None

    def start(self):
        self._task = cocotb.start_soon(self._run())
        return self._task

    def stop(self):
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def result(self):
        return self.cycles_checked, list(self.violations)

    async def _run(self):
        # Deliberately not reading any DUT signal here: at true
        # simulation time 0, before the first clock edge, unreset
        # internal state can read as 'X' and crash int() -- start with
        # assumed defaults and let the first loop iteration (after a
        # RisingEdge) establish the real values.
        prev_state = "IDLE"
        prev_addr = prev_write = prev_wdata = None

        while True:
            await RisingEdge(self.dut.PCLK)
            self.cycles_checked += 1
            if int(self.dut.PRESETn.value) == 0:
                prev_state = "IDLE"
                continue

            psel = int(self.dut.PSEL.value)
            penable = int(self.dut.PENABLE.value)
            addr = int(self.dut.PADDR.value)
            write = int(self.dut.PWRITE.value)
            wdata = int(self.dut.PWDATA.value)
            pready = int(self.dut.PREADY.value)

            if penable and not psel:
                self.violations.append(
                    Violation(self.cycles_checked, "penable_without_psel", "PENABLE asserted while PSEL is low")
                )

            if psel and not penable:
                cur_state = "SETUP"
            elif psel and penable:
                cur_state = "ACCESS"
            else:
                cur_state = "IDLE"

            if prev_state == "SETUP" and cur_state != "ACCESS":
                self.violations.append(
                    Violation(
                        self.cycles_checked,
                        "setup_not_one_cycle",
                        f"SETUP phase was not followed by ACCESS the next cycle (went to {cur_state} instead)",
                    )
                )

            if prev_state == "SETUP" and cur_state == "ACCESS":
                if addr != prev_addr or write != prev_write or (write and wdata != prev_wdata):
                    self.violations.append(
                        Violation(
                            self.cycles_checked,
                            "control_unstable",
                            f"PADDR/PWRITE/PWDATA changed between SETUP and ACCESS "
                            f"(setup: addr={prev_addr:#04x} write={prev_write} wdata={prev_wdata:#04x}; "
                            f"access: addr={addr:#04x} write={write} wdata={wdata:#04x})",
                        )
                    )

            if cur_state == "ACCESS" and not pready:
                self.violations.append(
                    Violation(self.cycles_checked, "pready_not_asserted", "PREADY was not asserted during ACCESS")
                )

            prev_state = cur_state
            prev_addr, prev_write, prev_wdata = addr, write, wdata
