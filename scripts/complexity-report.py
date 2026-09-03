#!/usr/bin/env python3
"""Complexity findings for a set of files, as GitLab Code Quality + a raw record.

Wraps the same complexity_lib the Claude Code PostToolUse hook uses
(.claude/hooks/), so the agent-time hook, the CI job and the
reduce-cyclomatic-complexity skill all judge code by one
complexity_thresholds.json rather than three copies of a number.

  complexity-report.py --files-from <list> --out-dir gate-findings [--rules ...]

Reads NUL-or-newline separated paths from <list> ("-" for stdin), writes
<out-dir>/complexity.json (raw record) and
<out-dir>/gl-code-quality-complexity.json (the GitLab merge request surface;
scripts/complexity-annotate.py turns the same raw record into GitHub
annotations). Exits 0 whether or not findings were found; a non-zero exit here
means the report itself failed to produce, which is what the CI job's `test -s`
and JSON-parse steps assert. Enforcement is a job-level setting
(allow_failure / continue-on-error), not this script's exit code.

WHY A FILE LIST AND NOT `--report .`. The gate is diff-scoped; the CI job builds
the list, and ci/gitlab/complexity.yml holds the measurements behind that choice.

RULE SELECTION. --rules picks which finding classes reach the report, and its
default is the subset the CI jobs run on — they pass no --rules of their own.
The classes have very different signal. Measured on the 64k-line TypeScript
monorepo this kit was extracted from: of the 326 findings a whole-tree run
reports, 179 are duplicate-block hits, and the largest single one is an
ESLint config file, where a "4-line block repeated at 8 sites" is the repeated
shape of a rule object — config data, not an extractable helper. file-length
flags a whole file, so it fires on any change that touches a large existing file
regardless of what the change did. complexity_lib has no notion of which is
which, so the filter lives here rather than in the shared library, and the
shared thresholds file keeps meaning the same thing everywhere. Both excluded
classes still run in the Claude Code hook, where a human sees them in context.
"""

import argparse
import json
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)
sys.path.insert(0, os.path.normpath(os.path.join(_SCRIPT_DIR, "..", ".claude", "hooks")))

from complexity_lib import analyze_file, load_thresholds, should_skip  # noqa: E402
from complexity_paths import is_contained, project_root, read_paths  # noqa: E402
from complexity_rules import (  # noqa: E402
    ALL_RULES,
    _entry,
    _record,
    split_finding,
)


def analyze_one(path, rules):
    """[(path, violation, thresholds), ...] for a single file.

    thresholds travels with each violation because load_thresholds is a
    nearest-wins search from the file's own directory, so two files in one
    diff can legitimately be judged against different configs.
    """
    thresholds = load_thresholds(os.path.dirname(path) or ".")
    if should_skip(path, thresholds):
        return []

    findings, notices = analyze_file(path, thresholds)
    for notice in notices:
        print(f"note: {path}: {notice}", file=sys.stderr)

    return [
        (path, v, thresholds)
        for finding in findings
        for v in split_finding(finding)
        if v.rule in rules
    ]


def collect(paths, rules):
    """[(path, violation, thresholds), ...] over every analyzable path.

    Missing files are skipped, not fatal: a merge request that deletes a file
    lists it in the diff, and the gate must not fail because a deleted path
    cannot be analyzed. Paths outside the checkout are skipped for the reason
    is_contained explains."""
    root = project_root()
    found = []
    for path in paths:
        if is_contained(path, root) and os.path.isfile(path):
            found.extend(analyze_one(path, rules))
    return found


def parse_args():
    """Parsed CLI arguments, with --rules already split and validated against
    ALL_RULES so an unknown rule fails here rather than silently reporting
    nothing."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--files-from", required=True, help="file with paths, or - for stdin")
    parser.add_argument("--out-dir", default="gate-findings")
    parser.add_argument(
        "--rules",
        default="cyclomatic-complexity,nesting-depth,function-length,parameter-count",
        help=f"comma-separated subset of: {','.join(ALL_RULES)}",
    )
    args = parser.parse_args()

    args.rules = [r.strip() for r in args.rules.split(",") if r.strip()]
    unknown = [r for r in args.rules if r not in ALL_RULES]
    if unknown:
        parser.error(f"unknown rule(s): {', '.join(unknown)}. Known: {', '.join(ALL_RULES)}")
    return args


def write_json(out_dir, name, payload):
    """Via a temp file then rename: the shell creates a redirect target before
    the writer runs, so writing straight to the final name leaves a zero-byte
    report behind on failure, and an always-upload artifact rule then ships
    that empty file as if it were the result."""
    tmp = os.path.join(out_dir, f".{name}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    os.replace(tmp, os.path.join(out_dir, name))


def main():
    """Analyze the listed paths and write both reports into --out-dir.

    Always returns 0: this gate reports, it does not fail the pipeline. The
    job is allow_failure and GitLab surfaces the findings from the artifacts.
    """
    args = parse_args()
    paths = read_paths(args.files_from)
    found = collect(paths, args.rules)
    entries = [_entry(path, v, thresholds) for path, v, thresholds in found]
    records = [_record(path, v) for path, v, _ in found]

    os.makedirs(args.out_dir, exist_ok=True)
    write_json(args.out_dir, "gl-code-quality-complexity.json", entries)
    write_json(
        args.out_dir,
        "complexity.json",
        {
            "files_examined": len(paths),
            "rules": args.rules,
            "finding_count": len(records),
            "findings": records,
        },
    )

    print(f"complexity: {len(records)} finding(s) across {len(paths)} changed file(s)")
    for r in records:
        print(f"  {r['path']}:{r['line']} [{r['rule']}] {r['message']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
