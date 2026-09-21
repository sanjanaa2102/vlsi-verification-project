"""Constrained-random value generation for apb_regblock tests.

Same philosophy as phase1_uart/uart_env/sequences.py: built on Python's
`random` module, which cocotb seeds and logs from COCOTB_RANDOM_SEED, so
a failing run reproduces with `make COCOTB_RANDOM_SEED=<seed>`. Values
are weighted toward corner cases rather than left fully uniform.

Unlike UART, this DUT's interesting randomness is less about a single
transaction's data and more about *which control-flow scenario* gets
exercised (start-while-disabled vs. start-while-busy vs. accepted, etc.)
and in what order -- so the scenario mix/ordering itself is randomized in
test_apb_regblock_random.py, using these functions for the underlying
data values, with guaranteed (not left-to-chance) coverage of every
scenario, mirroring uart_env.sequences.gen_sequence's guarantee approach.
"""

import random

CORNER_DATA = [0x00, 0xFF, 0x01, 0x80, 0x55, 0xAA]
INVALID_ADDRS = [0x01, 0x02, 0x03, 0x05, 0x09, 0x0D, 0x10, 0x20, 0xFF]


def random_data():
    if random.random() < 0.3:
        return random.choice(CORNER_DATA)
    return random.randint(0, 255)


def random_invalid_addr():
    return random.choice(INVALID_ADDRS)


def random_idle_cycles(max_gap=4):
    return random.randint(0, max_gap)
