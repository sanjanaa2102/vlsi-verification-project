"""Orchestrates formal property proofs (phase5_apb/formal/) for the
unified regression. Drives real SymbiYosys (sby), not a hand-rolled
substitute -- direct testing during Phase 7 showed hand-driving Yosys's
`sat` pass without sby is fragile (default optimization silently
stripped the assertion cells being checked).

Toolchain, all free/no-billing/no-sudo (verified, not assumed):
- yowasp-yosys / yowasp-yosys-smtbmc (Yosys compiled to WebAssembly,
  pip-installable, in requirements-lock.txt)
- z3-solver (pip-installable Z3 with a working `z3` CLI binary, in
  requirements-lock.txt)
- sby itself is not on PyPI (it's a small, ISC-licensed pure-Python tool
  with no setup.py to pip-install from git either) -- fetched once via a
  pinned-tag git clone into formal_tools/sby/ (gitignored, analogous to
  a build cache, not committed).
"""

import os
import re
import shutil
import subprocess

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORMAL_TOOLS_DIR = os.path.join(REPO_ROOT, "formal_tools")
SBY_DIR = os.path.join(FORMAL_TOOLS_DIR, "sby")
SBY_PY = os.path.join(SBY_DIR, "sbysrc", "sby.py")
SBY_GIT_URL = "https://github.com/YosysHQ/sby.git"
SBY_TAG = "v0.69"  # matches the yowasp-yosys version pinned in requirements-lock.txt

APB_FORMAL_DIR = os.path.join(REPO_ROOT, "phase5_apb", "formal")

PROPERTIES = ["apb_regblock_p1_pslverr", "apb_regblock_p2_no_restart", "apb_regblock_p3_busy_bounded"]


def ensure_sby():
    if os.path.exists(SBY_PY):
        return
    os.makedirs(FORMAL_TOOLS_DIR, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--branch", SBY_TAG, "--depth", "1", SBY_GIT_URL, SBY_DIR],
        check=True,
        capture_output=True,
    )


def ensure_tool_shims():
    """sby looks for plain `yosys` / `yosys-smtbmc` on PATH; the pip
    packages install as `yowasp-yosys` / `yowasp-yosys-smtbmc`. Tiny
    generated shims bridge the name, regenerated every call (cheap, a
    few bytes) rather than committed."""
    bin_dir = os.path.join(FORMAL_TOOLS_DIR, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    for shim_name, real_name in (("yosys", "yowasp-yosys"), ("yosys-smtbmc", "yowasp-yosys-smtbmc")):
        path = os.path.join(bin_dir, shim_name)
        with open(path, "w") as fh:
            fh.write(f"#!/bin/bash\nexec {real_name} \"$@\"\n")
        os.chmod(path, 0o755)
    return bin_dir


def _classify(output, sby_mode):
    if "successful proof by k-induction" in output:
        return "PASS", "unbounded (k-induction)"
    if re.search(r"DONE \(PASS, rc=0\)", output):
        if sby_mode == "prove":
            # basecase passed but induction did not also report the
            # k-induction success line -- report honestly as bounded,
            # never claim unbounded when induction didn't converge.
            return "PASS", "bounded (BMC basecase only -- induction did not converge)"
        return "PASS", "bounded (BMC)"
    if re.search(r"DONE \(FAIL, rc=\d+\)", output):
        return "FAIL", None
    return "ERROR", None


def run_property(name, timeout=180):
    """Runs one phase5_apb/formal/<name>.sby via real sby. Returns a
    dict with status, proof_type, and (on failure) counterexample
    artifact paths within the task's own output directory."""
    ensure_sby()
    bin_dir = ensure_tool_shims()
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ.get('PATH', '')}", PWD=APB_FORMAL_DIR)

    sby_file = f"{name}.sby"
    task_dir = os.path.join(APB_FORMAL_DIR, name)
    shutil.rmtree(task_dir, ignore_errors=True)

    with open(os.path.join(APB_FORMAL_DIR, sby_file)) as fh:
        sby_mode = "prove" if "mode prove" in fh.read() else "bmc"

    try:
        result = subprocess.run(
            ["python3", SBY_PY, "-f", sby_file],
            cwd=APB_FORMAL_DIR,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        output = result.stdout + result.stderr
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + (exc.stderr or "")
        timed_out = True

    if timed_out:
        return {"name": name, "status": "TIMEOUT", "proof_type": None, "raw_output": output, "task_dir": task_dir}

    status, proof_type = _classify(output, sby_mode)
    return {"name": name, "status": status, "proof_type": proof_type, "raw_output": output, "task_dir": task_dir}


def run_all(timeout=180):
    return [run_property(name, timeout=timeout) for name in PROPERTIES]


def capture_failure_artifacts(prop_result, results_dir):
    """Copies the counterexample VCD/testbench-replay/witness files sby
    already produced (in engine_0/, or engine_0.basecase/engine_0.induction
    for `mode prove`) into regression_results/failures/<prop>/."""
    failure_dir = os.path.join(results_dir, "failures", prop_result["name"])
    os.makedirs(failure_dir, exist_ok=True)

    with open(os.path.join(failure_dir, "sby_output.log"), "w") as fh:
        fh.write(prop_result.get("raw_output", ""))

    task_dir = prop_result["task_dir"]
    copied = []
    if os.path.isdir(task_dir):
        for root, _dirs, files in os.walk(task_dir):
            for f in files:
                if f.endswith((".vcd", "_tb.v", ".yw")):
                    src = os.path.join(root, f)
                    dst = os.path.join(failure_dir, f)
                    shutil.copy(src, dst)
                    copied.append(dst)
    return {"log": os.path.join(failure_dir, "sby_output.log"), "artifacts": copied}
