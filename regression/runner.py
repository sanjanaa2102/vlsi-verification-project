"""Orchestrates the unified UART + APB regression.

Deliberately a thin layer over commands that already exist and are
already independently verified (make, mutation_suite.py,
verible-verilog-lint) -- this module does not reimplement any
verification logic, it only runs existing commands as subprocesses and
collects their already-machine-readable output. No file in
phase1_uart/, phase5_apb/, or mutation/ is read for anything other than
their existing output artifacts (results.xml, coverage*.yml,
mutation_report.json).
"""

import os
import random
import shutil
import subprocess
import time

from . import parsers

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UART_DIR = os.path.join(REPO_ROOT, "phase1_uart")
APB_DIR = os.path.join(REPO_ROOT, "phase5_apb")
TEST0_DIR = os.path.join(REPO_ROOT, "test0")


def generate_seed():
    """A fresh seed for a random suite, generated before the suite runs
    so it is recorded even if the run then fails or hangs."""
    return random.SystemRandom().randint(1, 2**31 - 1)


def _run(cmd, cwd, timeout):
    # These Makefiles reference $(PWD), which GNU Make (when PWD isn't
    # otherwise defined in the Makefile) resolves from the *inherited*
    # PWD environment variable, not from subprocess.run's cwd= -- found
    # by direct testing, not assumed: without this, every DUT directory
    # resolved $(PWD) to run_regression.py's own launch directory instead
    # of the DUT directory, and every suite failed with "No rule to make
    # target .../dut.v".
    env = dict(os.environ, PWD=cwd)
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
        return result.returncode, result.stdout + result.stderr, False
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + (exc.stderr or "")
        return None, output, True


def run_make_suite(name, dut_dir, module=None, seed=None, timeout=120, waves=False):
    """Runs `make clean && make [MODULE=<module>] [COCOTB_RANDOM_SEED=<seed>]
    [WAVES=1]` in dut_dir, then parses dut_dir/results.xml.

    Returns a suite result dict. Raw command output is included so
    callers can persist it on failure, but is not meant to be kept in
    the final report (see report.py).
    """
    subprocess.run(["make", "clean"], cwd=dut_dir, capture_output=True, env=dict(os.environ, PWD=dut_dir))

    cmd = ["make"]
    if module:
        cmd.append(f"MODULE={module}")
    if seed is not None:
        cmd.append(f"COCOTB_RANDOM_SEED={seed}")
    if waves:
        cmd.append("WAVES=1")

    start = time.time()
    returncode, output, timed_out = _run(cmd, dut_dir, timeout)
    duration = time.time() - start

    results_xml = os.path.join(dut_dir, "results.xml")
    tests = []
    parse_error = None
    if os.path.exists(results_xml):
        try:
            tests = parsers.parse_results_xml(results_xml)
        except Exception as exc:  # malformed/missing XML is itself a real, reportable problem
            parse_error = str(exc)

    if timed_out:
        status = "TIMEOUT"
    elif parse_error or not tests:
        status = "ERROR" if returncode != 0 or not tests else "PASS"
    elif any(t["status"] == "FAIL" for t in tests):
        status = "FAIL"
    else:
        status = "PASS"

    return {
        "name": name,
        "dut_dir": dut_dir,
        "module": module,
        "seed": seed,
        "status": status,
        "tests": tests,
        "duration_s": round(duration, 3),
        "parse_error": parse_error,
        "_raw_output": output,  # underscore: stripped before the report is written, see report.py
    }


def capture_failure_artifacts(suite, results_dir):
    """For a failed single-make suite, saves the full simulator output
    and (re-running just that suite with WAVES=1) a waveform, under
    results_dir/failures/<suite name>/. Only called for suites that
    actually failed -- passing suites produce no extra artifacts."""
    failure_dir = os.path.join(results_dir, "failures", suite["name"])
    os.makedirs(failure_dir, exist_ok=True)

    with open(os.path.join(failure_dir, "simulator_output.log"), "w") as fh:
        fh.write(suite.get("_raw_output", ""))

    wave_suite = run_make_suite(
        suite["name"] + "_wave_capture",
        suite["dut_dir"],
        module=suite["module"],
        seed=suite["seed"],
        waves=True,
    )
    sim_build = os.path.join(suite["dut_dir"], "sim_build")
    fst_files = [f for f in os.listdir(sim_build) if f.endswith(".fst")] if os.path.isdir(sim_build) else []
    for f in fst_files:
        shutil.copy(os.path.join(sim_build, f), os.path.join(failure_dir, f))

    return {
        "log": os.path.join(failure_dir, "simulator_output.log"),
        "waveforms": [os.path.join(failure_dir, f) for f in fst_files],
    }


def run_coverage(dut_dir, yaml_filename):
    """Reads a coverage YAML file that a preceding suite already
    exported (via uart_env.coverage.export / apb_env.coverage.export).
    Returns {} if the file doesn't exist (e.g. the suite that would have
    produced it failed before reaching its report step)."""
    path = os.path.join(dut_dir, "sim_build", yaml_filename)
    if not os.path.exists(path):
        return {}
    return parsers.parse_coverage_yaml(path)


def run_lint(dut_dir, rtl_file, timeout=60):
    cmd = ["verible-verilog-lint", rtl_file]
    returncode, output, timed_out = _run(cmd, dut_dir, timeout)
    findings, unparsed = parsers.parse_lint_output(output)
    return {
        "file": rtl_file,
        "status": "TIMEOUT" if timed_out else ("CLEAN" if not findings and not unparsed else "FINDINGS"),
        "findings": findings,
        "unparsed": unparsed,
    }


def run_mutation(dut_dir, timeout=600):
    cmd = ["python", "mutation_suite.py"]
    returncode, output, timed_out = _run(cmd, dut_dir, timeout)
    report_path = os.path.join(dut_dir, "sim_build", "mutation_report.json")
    if timed_out or not os.path.exists(report_path):
        return {"status": "TIMEOUT" if timed_out else "ERROR", "raw_output": output}
    import json

    with open(report_path) as fh:
        data = json.load(fh)
    has_unknown = any(
        v.get("verdict") == "UNKNOWN"
        for m in data.get("mutants", [])
        for v in m.get("detection", {}).values()
    )
    return {"status": "ERROR" if has_unknown else "OK", **data}
