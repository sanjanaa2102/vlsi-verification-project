"""Generic, DUT-agnostic mutation-testing engine.

A "mutant" is a claim: replacing the golden RTL source with this modified
source should be detectable by a competent verification environment. A
"mechanism" is one way of running the regression against a mutant --
typically one cocotb test module -- so detection can be attributed to
whichever verification mechanism actually caught it (e.g. the scoreboard
vs. a protocol checker), not collapsed into an undifferentiated pass/fail.

This module has no UART-specific knowledge. A DUT directory supplies its
own list of Mutant and Mechanism objects (see
phase1_uart/mutation_suite.py for the UART manifest) and calls
run_suite(). The only assumption made about the DUT directory is the one
this project's Makefiles already share: `make clean && make
VERILOG_SOURCES=<abspath> MODULE=<mechanism.make_module>` builds and runs
that mechanism's cocotb test module against that RTL source, and cocotb's
own summary line contains `FAIL=<n>`. A future DUT (e.g. a planned
APB-Lite environment) that follows this same convention can reuse this
engine by writing its own manifest -- no runner code to duplicate.
"""

import dataclasses
import os
import re
import subprocess


@dataclasses.dataclass(frozen=True)
class Mutant:
    name: str
    file: str  # path relative to the DUT directory
    defect_category: str  # e.g. "off-by-one / boundary (timing)"
    description: str  # one-line plain-English description of the injected bug
    equivalent: bool = False  # true if verified undetectable in principle (excluded from scoring)
    equivalence_reason: str = ""


@dataclasses.dataclass(frozen=True)
class Mechanism:
    name: str  # e.g. "scoreboard", "protocol_checker"
    make_module: str  # value passed as MODULE=<...> -- doubles as "relevant test"
    description: str


@dataclasses.dataclass
class MutantResult:
    mutant: Mutant
    mechanism: Mechanism
    verdict: str  # "CAUGHT", "SURVIVED", "UNKNOWN"
    fail_count: int | None


def _run_make(dut_dir, verilog_source_abspath, mechanism, timeout):
    # These Makefiles reference $(PWD), which GNU Make resolves from the
    # *inherited* PWD environment variable (when not otherwise defined in
    # the Makefile), not from subprocess.run's cwd=. This was previously
    # masked in every prior use of this engine because it was always
    # invoked from a shell already cd'd into dut_dir, so the inherited
    # PWD happened to already match. Found by Phase 6's orchestrator
    # invoking this engine from the repo root instead, which surfaced it
    # as a real (if previously latent) robustness gap -- fixed here so
    # the engine works correctly regardless of the caller's own PWD.
    env = dict(os.environ, PWD=dut_dir)
    subprocess.run(["make", "clean"], cwd=dut_dir, capture_output=True, env=env)
    result = subprocess.run(
        ["make", f"VERILOG_SOURCES={verilog_source_abspath}", f"MODULE={mechanism.make_module}"],
        cwd=dut_dir,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    output = result.stdout + result.stderr
    m = re.search(r"FAIL=(\d+)", output)
    if m is None:
        return "UNKNOWN", None
    fail_count = int(m.group(1))
    return ("SURVIVED" if fail_count == 0 else "CAUGHT"), fail_count


def run_suite(dut_dir, mutants, mechanisms, timeout=120, restore_golden=True):
    """Run every non-equivalent mutant against every mechanism.

    Equivalent mutants (Mutant.equivalent=True) are skipped entirely --
    not run, not scored -- since by definition no mechanism could ever
    catch them; they exist in a manifest only as documentation of a
    reviewed-and-rejected mutant idea.

    Restores the DUT directory to a clean golden build afterward
    (best-effort) so the directory isn't left mid-mutant.
    """
    results = []
    for mutant in mutants:
        if mutant.equivalent:
            continue
        abspath = os.path.join(dut_dir, mutant.file)
        for mechanism in mechanisms:
            verdict, fail_count = _run_make(dut_dir, abspath, mechanism, timeout)
            results.append(MutantResult(mutant, mechanism, verdict, fail_count))
    if restore_golden:
        env = dict(os.environ, PWD=dut_dir)
        subprocess.run(["make", "clean"], cwd=dut_dir, capture_output=True, env=env)
        subprocess.run(["make"], cwd=dut_dir, capture_output=True, env=env)
    return results
