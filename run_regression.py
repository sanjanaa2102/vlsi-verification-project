#!/usr/bin/env python3
"""Unified UART + APB regression: one command, complete machine- and
human-readable evidence of what passed, what failed, coverage achieved,
and mutation effectiveness.

    python run_regression.py
    python run_regression.py --seed 12345       # pin both random suites
    python run_regression.py --skip-mutation     # faster local iteration
    python run_regression.py --skip-lint

phase2_llm/ is intentionally out of scope -- it is a separate research
track, not part of the UART + APB verification project this orchestrates.
"""

import argparse
import os
import sys

from regression import report as report_mod
from regression import runner

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(REPO_ROOT, "regression_results")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=None, help="Pin both random suites to this seed (default: fresh random seed each run, recorded in the report)")
    parser.add_argument("--skip-mutation", action="store_true", help="Skip mutation testing (fast local iteration; the full regression must still be run before relying on results)")
    parser.add_argument("--skip-lint", action="store_true", help="Skip lint")
    args = parser.parse_args()

    uart_seed = args.seed if args.seed is not None else runner.generate_seed()
    apb_seed = args.seed if args.seed is not None else runner.generate_seed()

    test_suites = []

    def run_and_record(name, dut_dir, module=None, seed=None):
        print(f"==> {name}")
        suite = runner.run_make_suite(name, dut_dir, module=module, seed=seed)
        print(f"    {suite['status']} ({sum(1 for t in suite['tests'] if t['status']=='PASS')}/{len(suite['tests'])} tests)")
        test_suites.append(suite)
        return suite

    # Coverage is extracted immediately after the suite that produces it,
    # not in a separate pass at the end: every suite's `make clean` wipes
    # the DUT's shared sim_build/ directory, so a later suite's clean
    # would otherwise delete an earlier suite's exported coverage YAML
    # before it's ever read (found by direct testing -- the first version
    # of this script produced an empty Coverage section).
    coverage = {}
    failure_artifacts = {}

    def maybe_capture_failure(suite):
        if suite["status"] != "PASS":
            print(f"==> capturing failure artifacts for {suite['name']}")
            failure_artifacts[suite["name"]] = runner.capture_failure_artifacts(suite, RESULTS_DIR)

    run_and_record("test0_sanity", runner.TEST0_DIR)
    maybe_capture_failure(test_suites[-1])

    run_and_record("uart_directed", runner.UART_DIR)
    maybe_capture_failure(test_suites[-1])

    suite = run_and_record("uart_coverage_directed", runner.UART_DIR, module="test_uart_tx_coverage")
    maybe_capture_failure(suite)
    coverage["uart_coverage_directed"] = runner.run_coverage(runner.UART_DIR, "coverage.yml")

    suite = run_and_record("uart_random", runner.UART_DIR, module="test_uart_tx_random", seed=uart_seed)
    maybe_capture_failure(suite)
    coverage["uart_random"] = runner.run_coverage(runner.UART_DIR, "coverage_random.yml")

    run_and_record("uart_checker_only", runner.UART_DIR, module="test_uart_tx_checker_only")
    maybe_capture_failure(test_suites[-1])

    run_and_record("apb_directed", runner.APB_DIR)
    maybe_capture_failure(test_suites[-1])

    suite = run_and_record("apb_random", runner.APB_DIR, module="test_apb_regblock_random", seed=apb_seed)
    maybe_capture_failure(suite)
    coverage["apb_random"] = runner.run_coverage(runner.APB_DIR, "coverage_random.yml")

    run_and_record("apb_checker_only", runner.APB_DIR, module="test_apb_regblock_checker_only")
    maybe_capture_failure(test_suites[-1])

    run_and_record("apb_latency_only", runner.APB_DIR, module="test_apb_regblock_latency_only")
    maybe_capture_failure(test_suites[-1])

    lint = {}
    if not args.skip_lint:
        print("==> uart_lint")
        lint["uart"] = runner.run_lint(runner.UART_DIR, "uart_tx.v")
        print(f"    {lint['uart']['status']} ({len(lint['uart']['findings'])} findings)")
        print("==> apb_lint")
        lint["apb"] = runner.run_lint(runner.APB_DIR, "apb_regblock.v")
        print(f"    {lint['apb']['status']} ({len(lint['apb']['findings'])} findings)")

    mutation = {}
    if not args.skip_mutation:
        print("==> uart_mutation (this runs many sub-invocations, please wait)")
        mutation["uart"] = runner.run_mutation(runner.UART_DIR)
        print(f"    {mutation['uart'].get('status')}")
        print("==> apb_mutation (this runs many sub-invocations, please wait)")
        mutation["apb"] = runner.run_mutation(runner.APB_DIR)
        print(f"    {mutation['apb'].get('status')}")

    # Strip raw simulator output before persisting the report -- it's
    # already saved separately for failing suites (capture_failure_artifacts)
    # and would otherwise bloat the JSON report for every passing suite too.
    for suite in test_suites:
        suite.pop("_raw_output", None)

    report = report_mod.build_report(REPO_ROOT, test_suites, coverage, mutation, lint, failure_artifacts)
    report_mod.write_json(report, os.path.join(RESULTS_DIR, "report.json"))
    report_mod.write_markdown(report, os.path.join(RESULTS_DIR, "report.md"))

    print()
    print(f"Overall status: {report['overall_status']}")
    print(f"Report: {os.path.join(RESULTS_DIR, 'report.json')}")
    print(f"Report: {os.path.join(RESULTS_DIR, 'report.md')}")
    if uart_seed is not None:
        print(f"UART random seed used: {uart_seed}")
    if apb_seed is not None:
        print(f"APB random seed used: {apb_seed}")

    return 0 if report["overall_status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
