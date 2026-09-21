"""Functional coverage model for apb_regblock, built on cocotb-coverage
(same library as phase1_uart, same free/no-billing toolchain).

Bins, and why:
- reg_class x direction: every register (including "invalid", an
  out-of-range/unmapped address) accessed via both read and write --
  this single cross also *is* the illegal-access coverage (STATUS-write,
  INTCLR-read, and invalid-write/invalid-read are exactly the 4 illegal
  cells of this cross), so a separate illegal-access CoverPoint would be
  redundant.
- start_control: the three distinct outcomes of writing CTRL.START --
  ignored while disabled, ignored while already busy, or actually
  accepted -- a control corner-case axis with no UART analogue.
- intclr_effect: whether an INTCLR write actually changed DONE (it was
  set) or was a no-op (it wasn't) -- small but real, since a design
  mistake in the write-1-to-clear logic could easily "work" for one case
  and not the other.
"""

from cocotb_coverage.coverage import CoverCross, CoverPoint, coverage_db

from .reference_model import reg_class

REG_CLASS_BINS = ["ctrl", "status", "data", "intclr", "invalid"]
DIRECTION_BINS = ["read", "write"]
START_CONTROL_BINS = ["start_while_disabled", "start_while_busy", "start_accepted"]
INTCLR_EFFECT_BINS = ["cleared_done", "noop"]


@CoverPoint(
    "top.reg_class",
    xf=lambda addr, direction: reg_class(addr),
    bins=REG_CLASS_BINS,
)
@CoverPoint(
    "top.direction",
    xf=lambda addr, direction: direction,
    bins=DIRECTION_BINS,
)
@CoverCross(
    "top.reg_class_x_direction",
    items=["top.reg_class", "top.direction"],
)
def sample_access(addr, direction):
    """Call once per issued transaction: direction is 'read' or 'write'."""


@CoverPoint(
    "top.start_control",
    xf=lambda outcome: outcome,
    bins=START_CONTROL_BINS,
)
def sample_start_control(outcome):
    """Call once per CTRL write that has bit1 (START) set."""


@CoverPoint(
    "top.intclr_effect",
    xf=lambda effect: effect,
    bins=INTCLR_EFFECT_BINS,
)
def sample_intclr(effect):
    """Call once per INTCLR write that has bit1 set."""


def report(logger):
    coverage_db.report_coverage(logger, bins=True)


def export(filename):
    coverage_db.export_to_yaml(filename)


def bin_percentage(name):
    return coverage_db[name].cover_percentage


def overall_percentage():
    return coverage_db["top"].cover_percentage
