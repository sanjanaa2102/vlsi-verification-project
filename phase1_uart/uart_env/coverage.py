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

Phase 3 adds two new axes for the dimensions constrained-random stimulus
newly explores (the four bins/cross above are unchanged from Phase 2):
- idle_gap_class: how long the bus was idle before a frame, at finer
  granularity than the binary tx_mode above (back-to-back vs gapped) --
  Phase 2's directed sweep only ever used one fixed gap length for
  "gapped", so it could not distinguish a 1-cycle gap from a 6-cycle gap.
- back_to_back_chain_length: whether a back-to-back run was exactly 2
  frames or 3+ -- Phase 2 never tested more than 2 chained frames.
See VERIFICATION_PLAN.md for the discussion of why the *old* 100%
coverage number stayed 100% (the old bins are coarse structural classes
that a handful of directed sends already saturates) and what these two
new axes add that it didn't capture.
"""

from cocotb_coverage.coverage import CoverCross, CoverPoint, coverage_db

from .reference_model import byte_class, gap_class

DATA_CLASS_BINS = ["zero", "all_ones", "alternating", "walking_one", "other"]
MODE_BINS = ["gapped", "back_to_back"]
GAP_CLASS_BINS = ["back_to_back", "small_gap", "large_gap"]
CHAIN_LENGTH_BINS = ["2", "3plus"]


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


@CoverPoint(
    "top.idle_gap_class",
    xf=lambda idle_cycles: gap_class(idle_cycles),
    bins=GAP_CLASS_BINS,
)
def sample_idle_gap(idle_cycles):
    """Call once per transaction with its idle_cycles value."""


@CoverPoint(
    "top.back_to_back_chain_length",
    xf=lambda length: "2" if length == 2 else "3plus",
    bins=CHAIN_LENGTH_BINS,
)
def sample_chain_length(length):
    """Call once per completed back-to-back chain (length >= 2 frames)."""


def report(logger):
    coverage_db.report_coverage(logger, bins=True)


def export(filename):
    coverage_db.export_to_yaml(filename)


def overall_percentage():
    return coverage_db["top"].cover_percentage


def bin_percentage(name):
    """Percentage for one specific named CoverPoint/CoverCross rather than
    the whole "top" aggregate.

    Needed because coverage_db is a process-wide singleton: importing this
    module registers every CoverPoint/CoverCross below regardless of
    whether a given test module actually samples all of them. A test
    module should assert closure only on the points it is actually
    responsible for driving, not on coverage_db["top"], which would also
    include points defined for a *different* test module that happens to
    share this process (see test_uart_tx_coverage.py and
    test_uart_tx_random.py for the two current owners).
    """
    return coverage_db[name].cover_percentage
