"""Pure-Python behavioral model of apb_regblock's register semantics.

No cocotb/DUT dependency, same philosophy as phase1_uart's reference
model: this is the "what should happen" half of the testbench. Unlike
UART's purely combinational model (one byte in, one fixed bit sequence
out), this DUT has real internal state (ENABLE/DATA/BUSY/DONE) and a
multi-cycle operation, so the model is a small state machine driven by a
sequence of register accesses -- "software-realistic": it assumes the
test polls STATUS (a real APB read) to observe BUSY/DONE, the same way
real firmware would, rather than tracking RTL-exact cycle timing itself.
Cycle-exact OP_LATENCY correctness is verified independently by
ApbLatencyChecker (see checker.py), not by this model -- see
VERIFICATION_PLAN.md for why a transaction-level model can't be trusted
to catch a pure latency defect on its own.
"""

ADDR_CTRL = 0x00
ADDR_STATUS = 0x04
ADDR_DATA = 0x08
ADDR_INTCLR = 0x0C
VALID_ADDRS = {ADDR_CTRL, ADDR_STATUS, ADDR_DATA, ADDR_INTCLR}


def is_illegal_write(addr):
    return addr not in VALID_ADDRS or addr == ADDR_STATUS


def is_illegal_read(addr):
    return addr not in VALID_ADDRS or addr == ADDR_INTCLR


def reg_class(addr):
    """Classify an address into a functional-coverage bin label."""
    if addr == ADDR_CTRL:
        return "ctrl"
    if addr == ADDR_STATUS:
        return "status"
    if addr == ADDR_DATA:
        return "data"
    if addr == ADDR_INTCLR:
        return "intclr"
    return "invalid"


class ApbRegblockModel:
    """Tracks the same observable state the RTL does, updated by
    apply_write()/apply_read() calls made in the exact order the driver
    issues them. "Operation completion" (BUSY clearing after OP_LATENCY
    cycles) is *not* time-driven here -- the test calls
    complete_pending_operation() once it has confirmed (via busy_o or by
    polling) that the real DUT has finished, and the model then applies
    the same data_reg <= data_reg+1 / done_reg <= 1 update the RTL does.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.enable = False
        self.data = 0
        self.busy = False
        self.done = False
        self._pending_start = False  # True once a start is accepted, until completion is confirmed

    def ctrl_read(self):
        return int(self.enable)  # START always reads back 0; bits[7:2] reserved=0

    def status_read(self):
        return (int(self.done) << 1) | int(self.busy)

    def apply_write(self, addr, data):
        """Returns expected PSLVERR (bool) for this write."""
        illegal = is_illegal_write(addr)
        if illegal:
            return True

        if addr == ADDR_CTRL:
            start_bit = bool(data & 0x02)
            enable_bit = bool(data & 0x01)
            # Mirrors the RTL: start condition checks the *previously
            # committed* enable value, not the bit just written in this
            # same access.
            if start_bit and self.enable and not self.busy:
                self.busy = True
                self._pending_start = True
            self.enable = enable_bit
        elif addr == ADDR_DATA:
            # A write to DATA while an operation is in flight is legal at
            # the bus level (not illegal_write) but its effect is
            # overwritten when the operation completes and increments
            # data_reg -- modeled as-is; a dedicated test exercises this.
            self.data = data
        elif addr == ADDR_INTCLR:
            if data & 0x02:
                self.done = False
        return False

    def apply_read(self, addr):
        """Returns (expected_prdata, expected_pslverr) for this read."""
        illegal = is_illegal_read(addr)
        if illegal:
            return 0x00, True
        if addr == ADDR_CTRL:
            return self.ctrl_read(), False
        if addr == ADDR_STATUS:
            return self.status_read(), False
        if addr == ADDR_DATA:
            return self.data, False
        raise AssertionError(f"unreachable: legal read address {addr:#x} not handled")

    def complete_pending_operation(self):
        """Call once the test has confirmed (via busy_o) the DUT's
        operation has finished -- applies the same update the RTL's
        countdown-expiry branch does."""
        if not self._pending_start:
            raise AssertionError("complete_pending_operation() called with no operation pending")
        self.busy = False
        self.done = True
        self.data = (self.data + 1) & 0xFF
        self._pending_start = False
