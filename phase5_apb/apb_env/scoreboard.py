"""Compares monitor-observed APB transactions against
ApbRegblockModel-predicted outcomes. All data-correctness checks live
here -- the driver only stimulates, the monitor only observes; this is
the only place a pass/fail judgement against expected register-map
behavior (including PSLVERR/legality -- a device-specific concern, not
an APB protocol rule, see checker.py) is made.

Note on error-response data: when PSLVERR is expected, PRDATA is treated
as implementation-defined (not checked) -- real APB does not mandate a
specific read-data value on an error response, and this DUT's "reads
0x00 on error" is an implementation detail, not a protocol requirement,
so asserting it here would conflate the two.
"""

from .reference_model import ApbRegblockModel


class ApbScoreboard:
    def __init__(self):
        self.model = ApbRegblockModel()
        self._expected = []
        self.checked = 0
        self.errors = []

    def expect_write(self, addr, data):
        err = self.model.apply_write(addr, data)
        self._expected.append(("write", addr, data, None, err))

    def expect_read(self, addr):
        rdata, err = self.model.apply_read(addr)
        self._expected.append(("read", addr, None, rdata, err))

    def complete_pending_operation(self):
        self.model.complete_pending_operation()

    def check_transaction(self, txn):
        if not self._expected:
            self.errors.append(
                f"unexpected transaction observed with no matching stimulus: "
                f"addr={txn.addr:#04x} write={txn.write}"
            )
            return

        kind, addr, wdata, exp_rdata, exp_err = self._expected.pop(0)
        self.checked += 1

        if txn.addr != addr:
            self.errors.append(f"address mismatch: expected {addr:#04x}, observed {txn.addr:#04x}")
        if txn.write != (kind == "write"):
            self.errors.append(f"direction mismatch at {addr:#04x}: expected {kind}")
        if txn.pslverr != exp_err:
            self.errors.append(
                f"PSLVERR mismatch at {addr:#04x} ({kind}): expected {exp_err}, observed {txn.pslverr}"
            )
        if kind == "write" and txn.wdata != wdata:
            self.errors.append(
                f"PWDATA mismatch at {addr:#04x}: expected {wdata:#04x}, observed {txn.wdata:#04x}"
            )
        if kind == "read" and not exp_err and txn.rdata != exp_rdata:
            self.errors.append(
                f"PRDATA mismatch at {addr:#04x}: expected {exp_rdata:#04x}, observed {txn.rdata:#04x}"
            )

    def result(self):
        return self.checked, list(self.errors)
