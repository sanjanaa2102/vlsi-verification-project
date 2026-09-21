"""apb_regblock mutation-testing manifest and entry point, built on the
generic engine in mutation/ (top-level, DUT-agnostic, unchanged since
Phase 4 -- proves it's genuinely reusable, not UART-specific).

Defect categories were assigned by reading each mutant's actual diff
against apb_regblock_golden.v, not guessed -- see VERIFICATION_PLAN.md
for the full review, including a candidate that was considered and
rejected for being effectively redundant with an existing UART defect
class rather than adding new signal.

Usage (from this directory):
    python mutation_suite.py
"""

import os
import sys

DUT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(DUT_DIR))

from mutation.framework import Mechanism, Mutant, run_suite
from mutation.report import export_report, print_report

MUTANTS = [
    Mutant(
        "mutant1_out_of_range_write_not_flagged",
        "apb_regblock_mutant1.v",
        "address decode / range check",
        "illegal_write drops the !addr_valid term -- a write to an out-of-range address no longer raises PSLVERR",
    ),
    Mutant(
        "mutant2_ctrl_readback_bit_swap",
        "apb_regblock_mutant2.v",
        "indexing / bit-order logic",
        "CTRL readback swaps bit0 (ENABLE) and bit1 (START) -- ENABLE=1 reads back as 0x02 instead of 0x01",
    ),
    Mutant(
        "mutant3_start_missing_busy_guard",
        "apb_regblock_mutant3.v",
        "control logic / missing guard condition",
        "START's condition drops the !busy_reg check -- a START write while already busy restarts the operation instead of being ignored",
    ),
    Mutant(
        "mutant4_latency_short",
        "apb_regblock_mutant4.v",
        "off-by-one / boundary (timing, short)",
        "operation completes after OP_LATENCY-1 cycles instead of exactly OP_LATENCY",
    ),
    Mutant(
        "mutant5_latency_long",
        "apb_regblock_mutant5.v",
        "off-by-one / boundary (timing, long)",
        "operation completes after OP_LATENCY+1 cycles instead of exactly OP_LATENCY",
    ),
    Mutant(
        "mutant6_intclr_wrong_bit",
        "apb_regblock_mutant6.v",
        "indexing / bit-order logic",
        "INTCLR checks PWDATA[0] instead of PWDATA[1] -- writing the documented clear pattern (bit1=1) never clears DONE",
    ),
    Mutant(
        "mutant7_data_not_incremented",
        "apb_regblock_mutant7.v",
        "missing computation / incorrect constant",
        "the operation completes (BUSY/DONE update correctly) but DATA is left unchanged instead of incremented",
    ),
    Mutant(
        "mutant8_status_write_permission_dropped",
        "apb_regblock_mutant8.v",
        "device-specific legality / missing permission check",
        "illegal_write drops the PADDR==ADDR_STATUS term -- writes to the read-only STATUS register are no longer flagged as illegal",
    ),
    Mutant(
        "mutant9_pready_never_asserted_on_write",
        "apb_regblock_mutant9.v",
        "APB bus interface / PREADY generation",
        "PREADY is tied to !PWRITE instead of 1 -- writes never complete (PREADY stays low during their ACCESS phase). Added "
        "specifically because the first 8 mutants are all register-semantics defects, none of which exercise the protocol "
        "checker's actual job (bus-interface invariants) -- see VERIFICATION_PLAN.md.",
    ),
]

MECHANISMS = [
    Mechanism("scoreboard", "test_apb_regblock", "Data-value and register-map-legality comparison against the reference model"),
    Mechanism("protocol_checker", "test_apb_regblock_checker_only", "Data-independent APB SETUP/ACCESS bus interface invariants"),
    Mechanism("latency_checker", "test_apb_regblock_latency_only", "Cycle-accurate OP_LATENCY check via the busy_o observability port"),
]

if __name__ == "__main__":
    results = run_suite(DUT_DIR, MUTANTS, MECHANISMS)
    equivalent = [m for m in MUTANTS if m.equivalent]
    print_report(results, equivalent_mutants=equivalent)
    export_report(results, os.path.join(DUT_DIR, "sim_build", "mutation_report.json"), equivalent_mutants=equivalent)
