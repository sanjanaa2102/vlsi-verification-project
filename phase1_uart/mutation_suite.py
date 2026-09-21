"""UART TX mutation-testing manifest and entry point, built on the
generic engine in mutation/ (top-level, DUT-agnostic).

Defect categories below were assigned by reading each mutant's actual
diff against uart_tx_golden.v, not guessed -- see VERIFICATION_PLAN.md
for the full defect-class review this manifest is based on, including
why mutants 7-9 were added and why one candidate mutant (removing
bit_idx/busy_reg resets from the `rst` branch) was reviewed and
deliberately *not* added: those resets are masked by the IDLE state's own
unconditional assignments, making that mutant equivalent (undetectable in
principle) rather than a real gap.

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
        "mutant1_stop_bit_polarity",
        "uart_tx_mutant1.v",
        "polarity / constant inversion",
        "Stop bit driven to 0 instead of 1 -- plausible copy-paste of the START state's line",
    ),
    Mutant(
        "mutant2_dropped_last_bit",
        "uart_tx_mutant2.v",
        "off-by-one / boundary (bit count)",
        "DATA state advances to STOP after 7 bits instead of 8 (bit_idx<7 vs bit_idx<6)",
    ),
    Mutant(
        "mutant3_short_start_bit",
        "uart_tx_mutant3.v",
        "off-by-one / boundary (timing, short)",
        "START segment held for CLKS_PER_BIT-1 cycles instead of CLKS_PER_BIT",
    ),
    Mutant(
        "mutant4_busy_stuck_high",
        "uart_tx_mutant4.v",
        "stuck-at / incorrect constant",
        "busy_reg driven to 1 instead of 0 in IDLE -- busy never deasserts",
    ),
    Mutant(
        "mutant5_msb_first_bug",
        "uart_tx_mutant5.v",
        "indexing / bit-order logic",
        "Data bits sent MSB-first instead of LSB-first (data_reg[7-bit_idx] vs data_reg[bit_idx])",
    ),
    Mutant(
        "mutant6_short_data_bits",
        "uart_tx_mutant6.v",
        "off-by-one / boundary (timing, short)",
        "Each DATA segment held for CLKS_PER_BIT-1 cycles instead of CLKS_PER_BIT",
    ),
    Mutant(
        "mutant7_incomplete_reset",
        "uart_tx_mutant7.v",
        "reset / initialization",
        "Reset no longer forces state back to IDLE -- FSM resumes from wherever it was when rst deasserts",
    ),
    Mutant(
        "mutant8_unlatched_data",
        "uart_tx_mutant8.v",
        "data capture / latching",
        "DATA state reads the live tx_data input instead of the latched data_reg",
    ),
    Mutant(
        "mutant9_long_start_bit",
        "uart_tx_mutant9.v",
        "off-by-one / boundary (timing, long)",
        "START segment held for CLKS_PER_BIT+1 cycles instead of CLKS_PER_BIT",
    ),
]

MECHANISMS = [
    Mechanism("scoreboard", "test_uart_tx", "Data-value comparison against the reference model"),
    Mechanism("protocol_checker", "test_uart_tx_checker_only", "Data-independent framing/timing invariants"),
    Mechanism(
        "coverage_directed",
        "test_uart_tx_coverage",
        "Broadened directed sweep, including the reset-mid-frame scenario "
        "-- test_uart_tx alone never exercises a reset after the FSM has "
        "left IDLE, so it structurally cannot catch a reset-handling bug",
    ),
]

if __name__ == "__main__":
    results = run_suite(DUT_DIR, MUTANTS, MECHANISMS)
    equivalent = [m for m in MUTANTS if m.equivalent]
    print_report(results, equivalent_mutants=equivalent)
    export_report(results, os.path.join(DUT_DIR, "sim_build", "mutation_report.json"), equivalent_mutants=equivalent)
