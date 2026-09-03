#!/usr/bin/env python3
"""GitHub Actions surface for a complexity.json written by complexity-report.py.

GitHub has no equivalent of GitLab's `reports: codequality`, so the two things
that put a finding in front of a reviewer are workflow-command annotations
(which land on the diff) and the job summary (which survives after the
annotation cap is hit). This writes both from the same raw record, so the
GitHub and GitLab surfaces can never disagree about what was found.

  complexity-annotate.py --findings gate-findings/complexity.json

Always exits 0. Enforcement is `continue-on-error` on the job, exactly as it
is `allow_failure` on the GitLab side.
"""

import argparse
import json
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

from complexity_rules import RULES_BY_ID  # noqa: E402

# GitHub renders at most 10 annotations of each level per step; everything past
# that is silently dropped. Cap explicitly and say so in the summary, rather
# than emit 200 commands and let the reviewer believe they saw all of them.
MAX_ANNOTATIONS_PER_LEVEL = 10

# major -> warning, minor -> notice. Never `error`: this gate is non-blocking,
# and an error annotation reads like a failed build next to the ones that are.
LEVEL_BY_SEVERITY = {"major": "warning", "minor": "notice"}


def escape_data(text):
    """Message text for a workflow command.

    A literal newline ends the command, so an unescaped one truncates the
    message and leaves the rest of it printed as plain log output. % must go
    first or it would double-escape the % this function introduces.
    """
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def escape_property(text):
    """A workflow command *property* value (file=, title=, ...).

    Properties are comma-separated with `:` ending the property list, so those
    two need escaping here on top of what escape_data covers — a function named
    `f(a, b)` in a title is enough to corrupt the command otherwise.
    """
    return escape_data(text).replace(":", "%3A").replace(",", "%2C")


def annotation(finding):
    """One `::warning file=...::message` workflow command line."""
    rule = RULES_BY_ID[finding["rule"]]
    level = LEVEL_BY_SEVERITY.get(rule.severity, "notice")
    props = ",".join([
        f"file={escape_property(finding['path'])}",
        f"line={finding['line']}",
        f"title={escape_property('complexity/' + finding['rule'])}",
    ])
    return f"::{level} {props}::{escape_data(finding['message'])}"


def emit_annotations(findings):
    """Print the workflow commands, capped per level. Returns the number of
    findings that were dropped by the cap."""
    emitted = {}
    dropped = 0
    for finding in findings:
        level = LEVEL_BY_SEVERITY.get(RULES_BY_ID[finding["rule"]].severity, "notice")
        if emitted.get(level, 0) >= MAX_ANNOTATIONS_PER_LEVEL:
            dropped += 1
            continue
        emitted[level] = emitted.get(level, 0) + 1
        print(annotation(finding))
    return dropped


def _row(finding):
    """One markdown table row.

    Escapes the cell separator: a function name may legitimately contain a pipe
    (a TypeScript union in a signature lizard captured), and one unescaped pipe
    shifts every later column in that row.
    """
    message = finding["message"].replace("|", "\\|")
    return f"| `{finding['path']}` | {finding['line']} | {finding['rule']} | {message} |"


def _cap_note(dropped):
    """The footnote that reconciles a short annotation list with a full table."""
    if not dropped:
        return []
    return [
        "",
        f"_{dropped} finding(s) are listed here only: GitHub renders "
        f"at most {MAX_ANNOTATIONS_PER_LEVEL} annotations per level._",
    ]


def summary_lines(report, dropped):
    """The job summary as markdown. Every finding appears here regardless of
    the annotation cap — this is the surface that stays complete."""
    findings = report["findings"]
    scope = (f"over {', '.join(report['rules'])} "
             f"across {report['files_examined']} changed file(s).")
    if not findings:
        return ["## Complexity gate", "", f"No findings {scope}"]
    header = [
        "## Complexity gate",
        "",
        f"**{report['finding_count']} finding(s)** {scope}",
        "",
        "| File | Line | Rule | Finding |",
        "| --- | --- | --- | --- |",
    ]
    return header + [_row(f) for f in findings] + _cap_note(dropped)


def write_summary(lines):
    """Append to the job summary when running under Actions, else stdout, so a
    local run of this script still shows what CI would show."""
    text = "\n".join(lines) + "\n"
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        print(text)
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--findings", default="gate-findings/complexity.json")
    args = parser.parse_args()

    with open(args.findings, encoding="utf-8") as f:
        report = json.load(f)

    dropped = emit_annotations(report["findings"])
    write_summary(summary_lines(report, dropped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
