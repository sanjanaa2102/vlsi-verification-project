"""Functional coverage model for uart_tx, built on cocotb-coverage.

Bins are chosen to be meaningful, not exhaustive-for-its-own-sake:
- tx_data_class: distinct structural byte patterns on the wire (see
  reference_model.byte_class for the rationale per bin).
- tx_mode: whether a frame started immediately after the previous one
  (back-to-back) or after idle time (gapped) -- these exercise different
  paths through the DUT's IDLE state re-entry.
- The cross of the two confirms every byte pattern was exercised under
  both framing conditions, not just some.
- reset_mid_transmission: whether the DUT's abort/recovery path (reset
  asserted partway through a frame) was exercised at least once.
"""

from cocotb_coverage.coverage import CoverCross, CoverPoint, coverage_db

from .reference_model import byte_class

DATA_CLASS_BINS = ["zero", "all_ones", "alternating", "walking_one", "other"]
MODE_BINS = ["gapped", "back_to_back"]


@CoverPoint(
    "top.tx_data_class",
    xf=lambda byte_val, mode: byte_class(byte_val),
    bins=DATA_CLASS_BINS,
)
@CoverPoint(
    "top.tx_mode",
    xf=lambda byte_val, mode: mode,
    bins=MODE_BINS,
)
@CoverCross(
    "top.tx_data_class_x_mode",
    items=["top.tx_data_class", "top.tx_mode"],
)
def sample_transaction(byte_val, mode):
    """Call once per successfully scoreboard-checked transaction."""


@CoverPoint(
    "top.reset_mid_transmission",
    xf=lambda scenario: scenario,
    bins=["occurred"],
)
def sample_reset_mid_transmission(scenario="occurred"):
    """Call once when a reset-during-transmission scenario is exercised.

    cocotb-coverage's CoverPoint requires the decorated function to be
    called with at least one positional argument (it inspects cb_args[0]
    internally) -- a truly zero-argument sample raises IndexError, so this
    takes one even though there is nothing meaningful to vary.
    """


def report(logger):
    coverage_db.report_coverage(logger, bins=True)


def export(filename):
    coverage_db.export_to_yaml(filename)


def overall_percentage():
    return coverage_db["top"].cover_percentage
