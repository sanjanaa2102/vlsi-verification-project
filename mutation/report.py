"""Formatting and export for mutation-suite results (mutation/framework.py).

No UART-specific knowledge here either -- operates only on the generic
Mutant/Mechanism/MutantResult types.
"""

import json
import os
from collections import defaultdict


def per_mutant_summary(results):
    """Group a flat MutantResult list by mutant.

    Returns {mutant: {mechanism_name: (verdict, fail_count)}}.
    """
    grouped = defaultdict(dict)
    for r in results:
        grouped[r.mutant][r.mechanism.name] = (r.verdict, r.fail_count)
    return grouped


def overall_verdict(mechanism_verdicts):
    """A mutant is CAUGHT overall if *any* mechanism caught it -- this is
    the number that answers "how effective is the verification
    environment as a whole", as distinct from any single mechanism's own
    score."""
    return "CAUGHT" if any(v == "CAUGHT" for v, _ in mechanism_verdicts.values()) else "SURVIVED"


def print_report(results, equivalent_mutants=(), logger=print):
    grouped = per_mutant_summary(results)
    mechanism_names = sorted({r.mechanism.name for r in results})

    logger("\n=== MUTATION TESTING REPORT ===")
    header = f"{'mutant':30s} {'defect category':38s} "
    header += " ".join(f"{m:20s}" for m in mechanism_names) + " overall"
    logger(header)
    logger("-" * len(header))

    caught_overall = 0
    for mutant, verdicts in grouped.items():
        row = " ".join(f"{verdicts.get(m, ('N/A', None))[0]:20s}" for m in mechanism_names)
        overall = overall_verdict(verdicts)
        if overall == "CAUGHT":
            caught_overall += 1
        logger(f"{mutant.name:30s} {mutant.defect_category:38s} {row} {overall}")

    total = len(grouped)
    logger("")
    logger(f"Total mutants scored: {total}")
    if equivalent_mutants:
        logger(
            f"Equivalent mutants excluded from scoring: {len(equivalent_mutants)} "
            f"({', '.join(m.name for m in equivalent_mutants)})"
        )
    logger(f"Caught (by at least one mechanism): {caught_overall}")
    logger(f"Survived (no mechanism caught it): {total - caught_overall}")
    if total:
        logger(f"Combined mutation score: {caught_overall / total * 100:.1f}%")

    for mech in mechanism_names:
        mech_results = [r for r in results if r.mechanism.name == mech]
        mech_caught = sum(1 for r in mech_results if r.verdict == "CAUGHT")
        if mech_results:
            logger(f"  {mech} alone: {mech_caught}/{len(mech_results)} ({mech_caught / len(mech_results) * 100:.1f}%)")

    by_category = defaultdict(list)
    for mutant, verdicts in grouped.items():
        by_category[mutant.defect_category].append(overall_verdict(verdicts))
    logger("\nBy defect category:")
    for cat, verdicts in sorted(by_category.items()):
        caught = sum(1 for v in verdicts if v == "CAUGHT")
        logger(f"  {cat}: {caught}/{len(verdicts)} caught")

    survivors = [mutant for mutant, verdicts in grouped.items() if overall_verdict(verdicts) == "SURVIVED"]
    if survivors:
        logger("\nSURVIVING mutants (no mechanism caught these):")
        for mutant in survivors:
            logger(f"  {mutant.name}: {mutant.description}")


def export_report(results, filename, equivalent_mutants=()):
    grouped = per_mutant_summary(results)
    data = {
        "mutants": [],
        "equivalent_mutants_excluded": [
            {"name": m.name, "reason": m.equivalence_reason} for m in equivalent_mutants
        ],
    }
    for mutant, verdicts in grouped.items():
        data["mutants"].append(
            {
                "name": mutant.name,
                "defect_category": mutant.defect_category,
                "description": mutant.description,
                "detection": {m: {"verdict": v, "fail_count": f} for m, (v, f) in verdicts.items()},
                "overall_verdict": overall_verdict(verdicts),
            }
        )
    total = len(grouped)
    caught = sum(1 for d in data["mutants"] if d["overall_verdict"] == "CAUGHT")
    data["summary"] = {
        "total": total,
        "caught": caught,
        "survived": total - caught,
        "mutation_score_pct": (caught / total * 100) if total else None,
    }
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, "w") as fh:
        json.dump(data, fh, indent=2)
