"""Parsing utilities for the regression orchestrator.

Deliberately reads existing, already-produced machine-readable artifacts
(cocotb's own results.xml, cocotb-coverage's exported YAML,
mutation_suite.py's exported JSON, verible-verilog-lint's structured
stdout) rather than regex-scraping human-oriented console text wherever
a real structured source already exists.
"""

import re
import xml.etree.ElementTree as ET

import yaml

LINT_LINE_RE = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+):(?P<col>[\d-]+):\s*(?P<message>.+?)\s*\[Style: [^\]]+\]\s*\[(?P<rule>[^\]]+)\]\s*$"
)


def parse_results_xml(path):
    """Returns a list of {name, classname, status, message} dicts, one
    per <testcase> in a cocotb-produced results.xml. status is "PASS" or
    "FAIL"."""
    tree = ET.parse(path)
    root = tree.getroot()
    cases = []
    for testcase in root.iter("testcase"):
        failure = testcase.find("failure")
        error = testcase.find("error")
        bad = failure if failure is not None else error
        cases.append(
            {
                "name": testcase.get("name"),
                "classname": testcase.get("classname"),
                "status": "FAIL" if bad is not None else "PASS",
                "message": (bad.get("message") if bad is not None else None),
            }
        )
    return cases


def parse_coverage_yaml(path):
    """Returns {coverage_point_name: cover_percentage} for every item in
    a cocotb-coverage exported YAML file."""
    with open(path) as fh:
        data = yaml.safe_load(fh)
    return {name: item.get("cover_percentage") for name, item in (data or {}).items()}


def parse_lint_output(text):
    """Returns a list of {file, line, col, message, rule} dicts, one per
    verible-verilog-lint finding line. Lines that don't match the
    standard `file:line:col: message [Style: X] [rule]` format (e.g. a
    tool crash) are returned separately as raw strings under
    "unparsed"."""
    findings = []
    unparsed = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = LINT_LINE_RE.match(line)
        if m:
            findings.append(m.groupdict())
        else:
            unparsed.append(line)
    return findings, unparsed
