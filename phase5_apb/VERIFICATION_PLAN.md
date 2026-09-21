# apb_regblock Verification Plan

## DUT: a small, functionally meaningful APB4-Lite register block

Not a plain register echo -- it models the most common real-world
register-block pattern: control/status registers plus an asynchronous
operation. APB signals: `PCLK, PRESETn` (active-**low**, standard AMBA
convention -- deliberately different polarity from UART's active-high
`rst`), `PADDR[7:0], PWRITE, PSEL, PENABLE, PWDATA[7:0], PRDATA[7:0],
PSLVERR` (`PREADY` tied high -- a valid zero-wait-state APB4 slave).
`busy_o` is an additional, verification-only observability port, not
part of the APB interface (see "Independently checking OP_LATENCY"
below).

| Addr | Register | Access | Semantics |
|---|---|---|---|
| 0x00 | CTRL | R/W | bit0 `ENABLE` (persistent); bit1 `START` (write-1 pulse, never stored, always reads 0); bits[7:2] reserved, always read 0 |
| 0x04 | STATUS | RO | bit0 `BUSY`, bit1 `DONE`; a write raises `PSLVERR` |
| 0x08 | DATA | R/W | 8-bit operand/result |
| 0x0C | INTCLR | WO | bit1=1 clears `DONE` (write-1-to-clear); a read raises `PSLVERR` |
| anything else | -- | -- | raises `PSLVERR` on read or write |

Operation semantics (deliberately precise, and directly tested): writing
CTRL with START=1 starts the operation **only if `ENABLE` was already
committed from a prior write** -- the condition checks the registered
`enable_reg`, not the bit just written in the same access, so writing
ENABLE and START together in one CTRL write does *not* start anything.
Once accepted, `BUSY` is set; after exactly `OP_LATENCY` (4) cycles,
`DATA <= DATA+1`, `BUSY` clears, `DONE` sets. A START while disabled or
already busy is ignored.

## Architecture: what's reused from UART, what's necessarily new

**Reused as-is:** the `mutation/` engine (proven below, unchanged);
the toolchain (Icarus/cocotb/cocotb-coverage/GTKWave/Verible); the
*pattern* -- driver (stimulus only) / monitor (autonomous decode) /
reference model (pure Python) / scoreboard (data-value comparison) /
protocol checker (data-independent invariants) / coverage / constrained
sequences / shared harness; the engineering discipline (verify timing
empirically via instrumentation, never hand-derive and trust it; bound
every wait loop; investigate survivors before "fixing" them).

**Necessarily DUT-specific:** all RTL; every `Apb*` class. APB's
blocking request/response shape is fundamentally different from UART's
async-frame shape (see `apb_env/driver.py`'s docstring), so no shared
base class was forced between the two DUTs' driver/monitor/scoreboard --
that would have been exactly the kind of abstraction-not-clearly-warranted
this project has avoided elsewhere. No pyuvm here either, for the same
reason it wasn't added to UART: plain cocotb classes already deliver
every required separation of concerns at this DUT's scope; UVM would be
a superficial wrapper, not added value.

**A new split not present in UART:** register-map legality (`PSLVERR`
correctness) lives in the **scoreboard**, not the protocol checker. The
protocol checker (`apb_env/checker.py`) covers only interface rules that
would apply to *any* APB4 slave (SETUP->ACCESS sequencing, PENABLE/PSEL
relationship, control/address/data stability, PREADY during ACCESS) --
which register addresses are legal is a fact about *this* device's
address map, not the APB protocol, so it belongs with the
reference-model-driven scoreboard instead.

## Independently checking OP_LATENCY

The scoreboard's reference model is deliberately "software-realistic" --
it only learns an operation finished when the test polls and observes
`BUSY=0`, the same way real firmware would. That means a
transaction-level comparison alone cannot distinguish a correct
`OP_LATENCY` from an off-by-one defect landing between two polls. Per
your Phase 5 refinement, `apb_env/latency_checker.py` (`ApbLatencyChecker`)
independently verifies this cycle-accurately, using the `busy_o`
observability port added to the RTL specifically for this purpose (not
part of the functional APB interface). It is attached via the shared
harness alongside the scoreboard and protocol checker on every test.

## Verification plan -> implementation

| Concern | Implementation |
|---|---|
| Stimulus | `ApbDriver`: blocking `write()`/`read()` implementing correct SETUP->ACCESS sequencing; `wait_busy_clear()` for test-level synchronization (see below) |
| Monitor | `ApbMonitor`: reconstructs every completed transaction (addr, direction, data, PSLVERR) from bus observation alone |
| Reference model | `ApbRegblockModel`: tracks ENABLE/DATA/BUSY/DONE, driven by the same write/read sequence the driver issues, in order |
| Scoreboard | `ApbScoreboard`: compares monitor-observed PRDATA/PSLVERR/PWDATA against the model, including register-map legality |
| Protocol checker | `ApbProtocolChecker`: pure APB interface invariants (see above), independent of the scoreboard |
| Latency checker | `ApbLatencyChecker`: cycle-accurate OP_LATENCY check via `busy_o`, independent of both |
| Functional coverage | `reg_class x direction` (10 cells -- covers every legal access *and* every illegal-access class), `start_control` (3), `intclr_effect` (2) |
| Constrained-random | `test_apb_regblock_random.py`: guaranteed presence of every scenario/coverage cell (deterministic, not seed-dependent), randomized order/data/idle-gap values within |
| Reset | `test_apb_reset_state`, `test_apb_reset_mid_operation` (PRESETn asserted mid-operation, same class of test that found a real bug in UART Phase 4) |
| Error/illegal transactions | `test_apb_illegal_accesses` (both illegal-write cases, both illegal-read cases), and their coverage cells in the random test |

### Why `wait_busy_clear()` uses `busy_o` instead of real APB polling reads

An earlier version polled `STATUS` over the real APB bus. The monitor
observes *every* bus transaction unconditionally and feeds it to the
scoreboard; since these polling reads were never registered as
"expected" (registering them runs into a circular ordering problem --
the model can only predict a poll's result if it already knows the
operation finished, which is precisely what polling exists to discover),
they showed up as unmatched transactions and desynchronized the
scoreboard's entire expected queue (found by direct testing, not
predicted). Using `busy_o` for pure test-level synchronization -- while
scoreboard/checker correctness checking stays fully black-box/cycle-
accurate -- avoids that without weakening either check.

## Real bugs and timing subtleties found by direct simulation (not assumed)

Consistent with the discipline established in UART Phases 2-4: every
timing assumption below was verified by instrumenting the simulator, not
derived and trusted.

1. **APB registers lacked Verilog initial values.** Unlike UART's
   `reg busy_reg = 1'b0;` style, the first RTL draft declared registers
   without initializers, so `busy_o` read `'X'` at true simulation time
   0 (before the first clock edge) and crashed `int()` in the checkers.
   Fixed by adding initial values to every register (matching UART's
   convention) and, defensively, by not reading any DUT signal
   synchronously before the first `RisingEdge` in `checker.py`/
   `latency_checker.py`.
2. **`busy_o` becomes observable one cycle *after* the triggering write
   returns**, not on the same cycle -- the same class of race already
   found and fixed in UART's `send_byte()` (Phase 2). `wait_busy_clear()`
   now explicitly waits for the rise before waiting for the fall.
3. **A scheduling race between two independent `busy_o` watchers**
   (`wait_busy_clear()` and `ApbLatencyChecker`, both polling the same
   signal) could let a test proceed and check `operations_checked`
   before the checker had finished recording the same event -- silently
   giving `ops_checked=0` with no error (a false-confidence bug: the
   assertion `not violations` trivially holds when nothing was measured
   at all). Found by explicitly asserting `ops_checked == 1` at relevant
   call sites, not by trusting the mechanism was "probably fine." Fixed
   with a 3-cycle settle margin in `wait_busy_clear()`, and every test
   that triggers a real operation now explicitly asserts the latency
   checker actually measured it.
4. **The latency checker didn't originally handle a reset occurring
   mid-measurement** (`test_apb_reset_mid_operation` interrupts an
   operation via `PRESETn`) -- it would have flagged the aborted,
   shorter-than-`OP_LATENCY` operation as a timing violation. Fixed the
   same way UART's checker excludes reset-aborted frames: `PRESETn`
   is checked inside the measurement loop, and a reset returns `None`
   (excluded from both the count and violation checking) rather than a
   real defect.

## Mutant review: defect categories, and a genuine test-stimulus gap found

Reviewed for realism and diversity before implementation (not
after-the-fact rationalization):

| Mutant | Defect category | Models |
|---|---|---|
| mutant1_out_of_range_write_not_flagged | address decode / range check | Forgot to flag out-of-range writes as illegal |
| mutant2_ctrl_readback_bit_swap | indexing / bit-order logic | ENABLE/START swapped in the CTRL readback mux |
| mutant3_start_missing_busy_guard | control logic / missing guard | START's busy guard dropped -- a retrigger while busy restarts the operation |
| mutant4_latency_short | off-by-one / boundary (timing, short) | Operation completes 1 cycle early |
| mutant5_latency_long | off-by-one / boundary (timing, long) | Operation completes 1 cycle late |
| mutant6_intclr_wrong_bit | indexing / bit-order logic | INTCLR checks the wrong data bit |
| mutant7_data_not_incremented | missing computation | Operation "completes" but DATA is never updated |
| mutant8_status_write_permission_dropped | device-specific legality | STATUS's read-only enforcement dropped |
| mutant9_pready_never_asserted_on_write | APB bus interface / PREADY generation | Writes never complete (`PREADY` tied to `!PWRITE`) |

mutant9 was added after the fact, deliberately: the first 8 are all
register-semantics defects (realistic and diverse on their own terms),
but none of them exercise the protocol checker's actual job -- in this
DUT, `PSEL`/`PENABLE` are pure inputs (the slave never generates them),
so the *only* slave-generated, protocol-relevant signal a mutation could
plausibly break is `PREADY`. Without mutant9, `protocol_checker` would
score 0/8 not because it's weak, but because no mutant happened to test
it; adding one real, plausible defect in its actual domain (a "forgot
this needs to complete on both reads and writes" bug) is a genuine gap
fix, not a manufactured mutant to move a metric -- see requirement 2's
instruction to add mutants only for genuinely missing defect classes.

**A candidate mutant considered and rejected:** varying `PREADY` to
depend on `PSEL` alone (`assign PREADY = PSEL;`) looked plausible at
first, but tracing it shows `PSEL` is already `1` throughout every
ACCESS phase by construction (the master holds it asserted through
SETUP and ACCESS) -- so this would be a true equivalent mutant,
indistinguishable from `PREADY=1` in every cycle that actually matters.
Not added.

### mutant3: a genuine test-stimulus gap, investigated and fixed (not force-fixed)

mutant3 initially **survived every mechanism**. Investigating (not
dismissing) found the real cause was in the test, not the environment's
capability: `test_apb_start_while_busy_is_ignored`'s retrigger write used
`data=0x02` (START only) a second time -- but *every* CTRL write
unconditionally updates `enable_reg <= PWDATA[0]`, so the *first*
START-only write already clears `enable_reg` as a side effect of
starting the operation. By the time a second START-only write was
issued, `enable_reg` was already 0 regardless of whether the busy guard
existed, so the guard's absence was never actually exercised. Confirmed
by direct simulation with internal signal instrumentation (`busy_reg`,
`op_count`, `done_reg`, `data_reg` traced cycle-by-cycle): several
retrigger-timing variants were tried and traced before finding one that
actually distinguishes golden from the mutant (re-asserting `ENABLE` via
its own separate write, immediately before immediately re-asserting
`START`, with no idle gap anywhere in the sequence -- any gap risks the
retrigger landing after the operation has already naturally completed).
Fixed in both `test_apb_regblock.py` and the equivalent random-test
scenario; verified the fix catches mutant3 (scoreboard: DATA reads
`0x02`, i.e. incremented twice, instead of the expected `0x01`) and does
not change golden-RTL behavior.

## Final mutation result (measured, not assumed)

| Mutant | Defect category | `latency_checker` | `protocol_checker` | `scoreboard` | Overall |
|---|---|---|---|---|---|
| mutant1_out_of_range_write_not_flagged | address decode / range check | SURVIVED | SURVIVED | CAUGHT | CAUGHT |
| mutant2_ctrl_readback_bit_swap | indexing / bit-order logic | SURVIVED | SURVIVED | CAUGHT | CAUGHT |
| mutant3_start_missing_busy_guard | control logic / missing guard | SURVIVED | SURVIVED | CAUGHT | CAUGHT |
| mutant4_latency_short | off-by-one (timing, short) | CAUGHT | SURVIVED | CAUGHT | CAUGHT |
| mutant5_latency_long | off-by-one (timing, long) | CAUGHT | SURVIVED | CAUGHT | CAUGHT |
| mutant6_intclr_wrong_bit | indexing / bit-order logic | SURVIVED | SURVIVED | CAUGHT | CAUGHT |
| mutant7_data_not_incremented | missing computation | SURVIVED | SURVIVED | CAUGHT | CAUGHT |
| mutant8_status_write_permission_dropped | device-specific legality | SURVIVED | SURVIVED | CAUGHT | CAUGHT |
| mutant9_pready_never_asserted_on_write | APB bus interface | SURVIVED | CAUGHT | CAUGHT | CAUGHT |

**Combined mutation score: 9/9 = 100%.** Per-mechanism:
`scoreboard` alone 9/9 (100%), `latency_checker` alone 2/9 (22.2%),
`protocol_checker` alone 1/9 (11.1%). The scoreboard dominates because
this DUT's mutants are overwhelmingly register-semantics defects (its
own actual attack surface); the other two mechanisms are narrower by
design and each demonstrably catches exactly what they were built to
catch (timing and interface defects respectively), not everything.
This 100% was earned by fixing one real test-stimulus gap (mutant3) and
adding one real missing-defect-class mutant (mutant9) -- not by
weakening or discarding anything.

## Lint

Verible found 6 findings on the first draft; 2 were fixed (`OP_LATENCY`
given an explicit `integer` type; `always @(*)` changed to
`always_comb`), verified not to change behavior. The remaining 4
(`ADDR_CTRL`/`ADDR_STATUS`/`ADDR_DATA`/`ADDR_INTCLR` lacking an explicit
storage type) are not fixed: giving them an explicit `logic [7:0]` type
triggers a *different* Verible rule (parameter naming convention) that
would require rewriting them away from the `ALL_CAPS_WITH_UNDERSCORES`
convention used consistently elsewhere in this project (including
UART's own localparams) -- not fixed here since these mutants didn't
exist yet when this was fixable without the "would need to regenerate
every mutant" constraint UART hit; the remaining findings are the same
kind of documented, deliberate trade-off as UART's.

## Phase 7: Formal Verification

Three properties, chosen because each requires exhaustive reasoning that
simulation (directed, random, or mutation-tested) does not provide --
not to collect "formal" as a keyword. Toolchain: `yowasp-yosys` +
`yowasp-yosys-smtbmc` (Yosys compiled to WebAssembly, pip-installable) +
`z3-solver` (pip-installable Z3 with a working `z3` CLI) + SymbiYosys
(`sby`, fetched at a pinned git tag by `regression/formal.py`, since it
isn't on PyPI) -- all free, no sudo/apt, no billing. Verified this
actually works end to end (not assumed) before committing to the design:
a hand-driven `yosys ... sat -verify` attempt, without `sby`, silently
optimized the assertion cell away -- confirming why `sby`'s carefully
sequenced passes are used instead of a hand-rolled substitute.

**Not SVA.** All three properties are plain procedural `assert`/`assume`
statements inside `always @(posedge PCLK)` blocks, verified to parse and
execute correctly. `property`/`sequence` SVA blocks were never tested and
are not used or claimed.

### P1 -- PSLVERR correctness

`assert (PSLVERR == (illegal_write || illegal_read))` during ACCESS, for
every `PADDR`/`PWRITE`/`PSEL`/`PENABLE` combination the solver can choose
(nothing is `assume`d away). This property is inherently combinational --
`PSLVERR` depends only on the current-cycle inputs, never on any internal
register -- so proving it at every BMC step already constitutes a
complete proof over the entire interface input space (all 256 `PADDR`
values x both directions), not merely a bounded-in-time claim. **Result:
PASS (BMC, depth 5; complete by the argument above, since the property
has no dependence on history).**

### P2 -- an accepted operation is never restarted while busy

The mutant3 (Phase 5) defect class: dropping the busy guard in
`apb_regblock.v`'s `CTRL` write logic lets a retrigger while busy restart
the operation. Genuinely temporal, not a same-cycle check: (1) watch for
`busy_o` rising 0->1 (acceptance); (2) latch the pre-operation `data_o`
value in the harness's own state; (3) leave every
`PADDR`/`PWRITE`/`PSEL`/`PENABLE`/`PWDATA` combination completely free
for as long as busy stays high, so the solver can choose *any* sequence
of interfering CTRL writes (including further ENABLE/START
combinations); (4) on `busy_o` falling 1->0 (completion), assert `data_o`
equals the latched value plus exactly one. `mode prove` (k-induction)
attempted first. **Result: PASS by successful k-induction -- an unbounded
proof, true for all time, not just up to a checked depth.**

**Scoping assumption, found necessary by direct testing, not assumed in
advance:** a DATA-address write while busy is legal at the bus level and
legitimately changes what value the eventual auto-increment operates on
(`apb_env/reference_model.py`'s `apply_write` already models this). An
early version of this property, without excluding it, produced a
counterexample that was really just this legal, already-understood
interaction -- not a restart bug. Excluding DATA writes while busy
(`assume (!(PSEL && PWRITE && PADDR == 8'h08))` when `busy_o`) narrows
the property to what it is actually about (the CTRL/START retrigger
guard) instead of silently conflating two unrelated behaviors. CTRL
writes, including every ENABLE/START combination and illegal accesses,
remain completely unconstrained throughout.

### P3 -- BUSY is never held for more than OP_LATENCY consecutive cycles

Generalizes the mutant4/mutant5/busy-stuck-style defect classes (each
mutation testing's *specific hand-injected bug*) into one exhaustive
claim: no reachable state and no sequence of interfering writes can hold
`busy_o` longer than the DUT's own configured latency. The bound is not
an arbitrary constant: the harness takes `OP_LATENCY` as its own
parameter and passes it straight through to the `apb_regblock` instance,
so the property's threshold and the DUT's actual latency can never drift
apart. `mode prove` attempted first. **Result: PASS by successful
k-induction -- an unbounded proof.**

### A real toolchain limitation found and worked around (not papered over)

Hierarchical cross-module references (`dut.busy_reg`, `dut.data_reg`)
were the first approach tried for P2/P3's white-box bookkeeping. Direct
testing found this toolchain does not reliably model them: a *trivial
tautology*, `assert (busy_o == dut.busy_reg)` -- true by definition, since
`apb_regblock.v` literally assigns `busy_o = busy_reg` -- produced a false
counterexample. Confirmed this wasn't a mistake in the property logic by
replaying the exact same counterexample input sequence through Icarus (a
simulator this project fully trusts) and observing correct behavior
throughout, with no assertion violation. **Fix:** `data_o`, a
verification-only observability port, was added to `apb_regblock.v`
(mirrors `busy_o`'s existing Phase 5 precedent exactly -- see the RTL
comment). P2/P3 now observe `busy_o`/`data_o` only, both real ports; the
same tautology check passes correctly through a port. This is a targeted
fix for a confirmed tool limitation, not a change to make a property
pass -- no functional RTL behavior changed, and it required a second
genuinely necessary fix (`initial assume (!PRESETn)`, since BMC is
otherwise free to start from a state where reset never occurs at all,
found the same way: a counterexample trace that literally never resets).

Both fixes, and the DATA-write scoping assumption above, were found by
instrumenting and replaying actual counterexamples through Icarus or
inspecting the generated testbench replay -- the same "verify
empirically, don't assume" discipline used throughout this project, not
guessed in advance.

### Demonstrated against real faults, not just golden RTL

- P1 against the existing `apb_regblock_mutant8.v` (STATUS write-
  protection dropped): genuine counterexample, real `trace.vcd` +
  `trace_tb.v` produced.
- P2 against `phase5_apb/formal/apb_regblock_fixture_fault_p2p3.v` (a
  dedicated formal-only fixture reproducing mutant3's exact bug on the
  `data_o`-equipped RTL -- deliberately *not* one of the 9 tracked
  mutation-suite mutants, none of which have `data_o`, so mutation
  testing's existing mutants and results stay completely untouched):
  both the BMC basecase and the induction step correctly FAIL with a
  genuine counterexample.

### Coexistence with existing infrastructure

Lives entirely in `phase5_apb/formal/`. Does not modify `apb_env/`, any
existing test file, `mutation_suite.py`, or `mutation/framework.py`.
Independent of the simulation scoreboard/protocol/latency checkers --
no Python code, no cocotb, nothing shared; the only overlap is that both
happen to check related behaviors from different angles (exhaustive
formal proof vs. concrete-trace simulation), which is the point, not
duplication. Not integrated into `mutation_suite.py` as a 4th mechanism
in this phase -- noted as a natural but explicitly deferred future
extension, consistent with not redesigning the mutation framework.

Included in the unified regression (`run_regression.py`, its own
"Formal Verification" report section, `--skip-formal` to omit) and in CI
(`.github/workflows/regression.yml`) -- see `regression/formal.py`.
Kept practical: each property proved in about a second against this
DUT's actual (small) reachable state space.

## How to run

```bash
cd phase5_apb
make                                    # directed regression (test_apb_regblock.py)
make MODULE=test_apb_regblock_random    # constrained-random regression
make MODULE=test_apb_regblock_random COCOTB_RANDOM_SEED=<seed>   # reproduce a run
make MODULE=test_apb_regblock_checker_only   # protocol checker in isolation
make MODULE=test_apb_regblock_latency_only   # latency checker in isolation
cat sim_build/coverage_random.yml       # exported coverage report

verible-verilog-lint apb_regblock.v

python mutation_suite.py                # full mutation report (uses mutation/, DUT-agnostic)

# Formal (from the repo root -- fetches sby automatically on first use):
python run_regression.py --skip-mutation --skip-lint   # includes formal by default
```
