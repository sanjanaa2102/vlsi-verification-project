"""Constrained-random stimulus generation for uart_tx.

Built on Python's `random` module rather than a private RNG instance:
cocotb already seeds the global `random` module from COCOTB_RANDOM_SEED
and logs the value at the start of every run ("Seeding Python random
module with <seed>"). Reusing that module means a failing random run is
reproduced exactly by rerunning with
`make MODULE=test_uart_tx_random COCOTB_RANDOM_SEED=<seed>` -- no
separate seed-tracking mechanism is needed.

Constraints are deliberate, not "roll the dice and hope":
- byte values are weighted ~30% toward the same structurally-interesting
  corner-case values the directed coverage sweep uses, ~70% uniform
  random over the full byte range -- uniform-random alone would rarely
  hit an exact corner value like 0x00 by chance.
- idle gaps before a frame are bounded to [0, MAX_IDLE_GAP] cycles; an
  unbounded gap would only waste simulation time, not exercise new DUT
  behavior.
- every generated sequence *guarantees* (not leaves to chance) at least
  one exactly-2 back-to-back chain, one 3+ back-to-back chain, one small
  gap, and one large gap, so coverage closure on those bins is
  deterministic across every seed rather than flaky.
"""

import random

CORNER_BYTES = [0x00, 0xFF, 0x01, 0x80, 0x55, 0xAA, 0x02, 0x40]
MAX_IDLE_GAP = 6
CORNER_BYTE_PROBABILITY = 0.3


def random_byte():
    if random.random() < CORNER_BYTE_PROBABILITY:
        return random.choice(CORNER_BYTES)
    return random.randint(0, 255)


def random_idle_cycles():
    return random.randint(0, MAX_IDLE_GAP)


def random_transaction():
    return {"byte_val": random_byte(), "idle_cycles": random_idle_cycles()}


def gen_sequence(n_random_before=10, n_random_after=10):
    """Build a stimulus sequence as explicit deliberate sections, each
    individually randomized in content but structurally guaranteed to
    exercise every corner case the coverage model tracks:

      [n_random_before random txns]
      [gapped, back_to_back]                  -- exactly-2 chain
      [gapped, back_to_back, back_to_back]     -- 3+ chain
      [small gap (1-2 cycles)]
      [large gap (3-6 cycles)]
      [n_random_after random txns]

    Returns a list of {"byte_val", "idle_cycles"} dicts.
    """
    seq = [random_transaction() for _ in range(n_random_before)]

    seq.append({"byte_val": random_byte(), "idle_cycles": random.randint(1, MAX_IDLE_GAP)})
    seq.append({"byte_val": random_byte(), "idle_cycles": 0})

    seq.append({"byte_val": random_byte(), "idle_cycles": random.randint(1, MAX_IDLE_GAP)})
    seq.append({"byte_val": random_byte(), "idle_cycles": 0})
    seq.append({"byte_val": random_byte(), "idle_cycles": 0})

    seq.append({"byte_val": random_byte(), "idle_cycles": random.randint(1, 2)})
    seq.append({"byte_val": random_byte(), "idle_cycles": random.randint(3, MAX_IDLE_GAP)})

    seq += [random_transaction() for _ in range(n_random_after)]
    return seq


def chain_lengths(stimulus):
    """Lengths (in frames) of every maximal back-to-back chain of 2 or
    more in a generated sequence -- a lone gapped frame is not a chain."""
    lengths = []
    current = 1
    for i, txn in enumerate(stimulus):
        if i > 0 and txn["idle_cycles"] == 0:
            current += 1
        else:
            if current >= 2:
                lengths.append(current)
            current = 1
    if current >= 2:
        lengths.append(current)
    return lengths
