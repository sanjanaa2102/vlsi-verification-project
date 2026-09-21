"""Builds and renders the unified regression report: one JSON file
(machine-readable) and one Markdown file (human-readable), covering
tests, coverage, mutation, and lint as separate sections -- never
collapsed into a single pass/fail percentage.
"""

import datetime
import json
import os
import subprocess


def _git_commit(repo_root):
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=repo_root, capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip() or None
    except Exception:
        return None


def build_report(repo_root, test_suites, coverage, mutation, lint, failure_artifacts):
    """test_suites: list of suite dicts from runner.run_make_suite (with
    _raw_output already stripped by the caller).
    coverage: {suite_name: {point: pct}}
    mutation: {"uart": {...}, "apb": {...}}
    lint: {"uart": {...}, "apb": {...}}
    failure_artifacts: {suite_name: {"log":..., "waveforms": [...]}}
    """
    test_status_ok = all(s["status"] == "PASS" for s in test_suites)
    mutation_status_ok = all(m.get("status") != "ERROR" for m in mutation.values())
    overall_status = "PASS" if (test_status_ok and mutation_status_ok) else "FAIL"

    return {
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "git_commit": _git_commit(repo_root),
        "overall_status": overall_status,
        "test_suites": test_suites,
        "coverage": coverage,
        "mutation": mutation,
        "lint": lint,
        "failure_artifacts": failure_artifacts,
    }


def write_json(report, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(report, fh, indent=2)


def _fmt_pct(v):
    return f"{v:.1f}%" if isinstance(v, (int, float)) else "n/a"


def render_markdown(report):
    lines = []
    lines.append("# Regression Report")
    lines.append("")
    lines.append(
        f"Generated: {report['timestamp_utc']} | Commit: `{report['git_commit'] or 'unknown'}` | "
        f"**Overall: {report['overall_status']}**"
    )
    lines.append("")

    lines.append("## Test Suites")
    lines.append("")
    lines.append("| Suite | Status | Tests | Pass | Fail | Seed | Duration (s) |")
    lines.append("|---|---|---|---|---|---|---|")
    for s in report["test_suites"]:
        n = len(s["tests"])
        p = sum(1 for t in s["tests"] if t["status"] == "PASS")
        f = n - p
        lines.append(
            f"| {s['name']} | {s['status']} | {n} | {p} | {f} | {s['seed'] if s['seed'] is not None else '-'} | {s['duration_s']} |"
        )
    lines.append("")

    failed = [s for s in report["test_suites"] if s["status"] != "PASS"]
    if failed:
        lines.append("### Failed test detail")
        lines.append("")
        for s in failed:
            for t in s["tests"]:
                if t["status"] == "FAIL":
                    lines.append(f"- **{s['name']}** / `{t['name']}`: {t['message']}")
            if s["name"] in report["failure_artifacts"]:
                art = report["failure_artifacts"][s["name"]]
                lines.append(f"  - simulator log: `{art['log']}`")
                for w in art["waveforms"]:
                    lines.append(f"  - waveform: `{w}`")
        lines.append("")

    lines.append("## Functional Coverage")
    lines.append("")
    for suite_name, points in report["coverage"].items():
        if not points:
            continue
        lines.append(f"### {suite_name}")
        lines.append("")
        for point, pct in points.items():
            lines.append(f"- `{point}`: {_fmt_pct(pct)}")
        lines.append("")

    lines.append("## Mutation Testing")
    lines.append("")
    for dut_name, data in report["mutation"].items():
        lines.append(f"### {dut_name}")
        lines.append("")
        if data.get("status") == "ERROR":
            lines.append("**ERROR running mutation suite** -- see raw output in the JSON report.")
            lines.append("")
            continue
        summary = data.get("summary", {})
        lines.append(
            f"Total: {summary.get('total')} | Caught: {summary.get('caught')} | "
            f"Survived: {summary.get('survived')} | Combined score: {_fmt_pct(summary.get('mutation_score_pct'))}"
        )
        lines.append("")

        mechanism_names = sorted({mech for m in data.get("mutants", []) for mech in m.get("detection", {})})
        mutants = data.get("mutants", [])
        for mech in mechanism_names:
            caught = sum(1 for m in mutants if m["detection"].get(mech, {}).get("verdict") == "CAUGHT")
            lines.append(f"- `{mech}` alone: {caught}/{len(mutants)} ({_fmt_pct(100 * caught / len(mutants) if mutants else None)})")
        lines.append("")

        header = ["Mutant", "Defect category"] + mechanism_names + ["Overall"]
        lines.append("| " + " | ".join(header) + " |")
        lines.append("|" + "---|" * len(header))
        for m in data.get("mutants", []):
            row = [m["name"], m["defect_category"]]
            row += [m["detection"].get(mech, {}).get("verdict", "n/a") for mech in mechanism_names]
            row += [m["overall_verdict"]]
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")

    lines.append("## Lint")
    lines.append("")
    for dut_name, data in report["lint"].items():
        lines.append(f"### {dut_name}: `{data['file']}` -- {data['status']} ({len(data['findings'])} findings)")
        for f in data["findings"]:
            lines.append(f"- {f['file']}:{f['line']}:{f['col']}: {f['message']} `[{f['rule']}]`")
        lines.append("")

    return "\n".join(lines)


def write_markdown(report, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(render_markdown(report))
