"""Compares monitor-observed transactions against the reference model.

All correctness checks live here -- the driver only stimulates and the
monitor only decodes. Errors are collected rather than raised immediately
so a single run surfaces every mismatch instead of stopping at the first.
"""

from .reference_model import expected_frame_bits


class UartTxScoreboard:
    def __init__(self):
        self._expected = []
        self.checked = 0
        self.errors = []

    def expect(self, byte_val):
        self._expected.append(byte_val)

    def check_transaction(self, txn):
        if txn.aborted:
            return

        if not self._expected:
            self.errors.append(
                f"unexpected transaction observed with no matching stimulus: "
                f"{txn.byte_val:#x}"
            )
            return

        expected_byte = self._expected.pop(0)
        self.checked += 1

        exp_bits = expected_frame_bits(expected_byte)
        for seg_idx, (samples, exp_val) in enumerate(zip(txn.segment_samples, exp_bits)):
            if not all(s == exp_val for s in samples):
                self.errors.append(
                    f"byte {expected_byte:#x} segment {seg_idx}: expected constant "
                    f"{exp_val} for the full bit period, got {samples}"
                )

        if txn.byte_val != expected_byte:
            self.errors.append(
                f"byte mismatch: expected {expected_byte:#x}, got {txn.byte_val:#x}"
            )

        if not txn.busy_ok:
            self.errors.append(
                f"byte {expected_byte:#x}: tx_busy did not deassert after the stop bit"
            )

    def result(self):
        return self.checked, list(self.errors)
