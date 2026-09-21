"""Pure-Python golden model for a UART 8N1 TX frame.

No cocotb or DUT dependency on purpose: this is the "what should happen"
half of the testbench, kept independent from "what did happen" (the
monitor) so the scoreboard is comparing two independently-derived views.
"""

CLKS_PER_BIT_DEFAULT = 4


def expected_frame_bits(byte_val):
    """Expected serial bit sequence for one 8N1 frame.

    Order: [start(0), data0..data7 (LSB first), stop(1)] -- 10 segments,
    each held for CLKS_PER_BIT cycles on the wire.
    """
    if not 0 <= byte_val <= 0xFF:
        raise ValueError(f"byte_val out of range: {byte_val:#x}")
    bits = [0]
    bits += [(byte_val >> i) & 1 for i in range(8)]
    bits.append(1)
    return bits


def byte_class(byte_val):
    """Classify a byte value into a functional-coverage bin label.

    Bins were chosen because they exercise structurally distinct bit
    patterns on the serial line: an all-idle-level byte, an all-opposite
    byte, a toggling byte, a byte with a single bit set (isolates one bit
    position), and everything else.
    """
    if byte_val == 0x00:
        return "zero"
    if byte_val == 0xFF:
        return "all_ones"
    if byte_val in (0x55, 0xAA):
        return "alternating"
    if byte_val != 0 and (byte_val & (byte_val - 1)) == 0:
        return "walking_one"
    return "other"


def gap_class(idle_cycles):
    """Classify the idle gap before a transmission into a coverage bin.

    Distinct from byte_class: this is a timing-dimension classification
    (how long the bus was idle before this frame started), independent of
    what data the frame carries.
    """
    if idle_cycles == 0:
        return "back_to_back"
    if idle_cycles <= 2:
        return "small_gap"
    return "large_gap"
