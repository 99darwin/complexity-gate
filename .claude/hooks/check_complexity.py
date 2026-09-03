#!/usr/bin/env python3
"""
check_complexity.py — Claude Code PostToolUse hook entrypoint.

Runs after Claude writes or edits a file. Analyzes it for cyclomatic
complexity, function length, nesting depth, parameter count, file size, and
in-file duplicate blocks (see complexity_lib.py for the actual checks — this
file is deliberately just wiring, kept under its own thresholds).

Depending on complexity_thresholds.json's "mode":

  warn  -> always exits 0, findings are printed so Claude/the user can see them.
  block -> exits 2 (report on stderr) when a real violation is found, which
           Claude Code treats as a blocking error: Claude sees the reason and
           must address it before moving on. A missing `lizard` install never
           blocks — that's a notice, not a finding.

Wire it up in .claude/settings.json:

  {
    "hooks": {
      "PostToolUse": [
        {
          "matcher": "Write|Edit|MultiEdit",
          "hooks": [
            {"type": "command", "command": "python3 .claude/hooks/check_complexity.py"}
          ]
        }
      ]
    }
  }

Also runnable standalone for the reduce-cyclomatic-complexity skill / a human:

  python3 .claude/hooks/check_complexity.py --report path/to/file.py
  python3 .claude/hooks/check_complexity.py --report path/to/dir/

Only dependency: lizard (multi-language: Python, JS/TS, Go, Java, C/C++,
Ruby, Swift, C#, Objective-C — one analyzer, no per-language tool sprawl).
Install the version-and-hash-pinned closure the CI gate uses, so the hook and
the gate can never disagree about a file:

  pip install --require-hashes -r scripts/complexity-requirements.txt
"""

import json
import os
import sys

from complexity_lib import analyze_file, format_report, load_thresholds, should_skip


def _extract_file_path(payload):
    """None unless payload describes a Write/Edit/MultiEdit on a file that
    actually exists on disk. Isolated so run_as_hook reads as one guard-
    clause-per-line instead of one big nested condition."""
    if payload.get("tool_name") not in ("Write", "Edit", "MultiEdit"):
        return None
    file_path = (payload.get("tool_input") or {}).get("file_path")
    if not file_path or not os.path.isfile(file_path):
        return None
    return file_path


def run_as_hook():
    """PostToolUse entrypoint: read the tool payload on stdin, analyze the file
    it wrote. Returns the process exit code — 2 only when a real finding is
    paired with mode=block, 0 in every other case including malformed input."""
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # malformed input should never block a write

    file_path = _extract_file_path(payload)
    if not file_path:
        return 0

    thresholds = load_thresholds(os.path.dirname(file_path))
    if should_skip(file_path, thresholds):
        return 0

    findings, notices = analyze_file(file_path, thresholds)
    if not findings and not notices:
        return 0

    report = format_report(file_path, findings, notices)
    blocking = findings and thresholds.get("mode") == "block"
    print(report, file=sys.stderr if blocking else sys.stdout)
    # Exit code 2: Claude Code surfaces stderr to Claude as a blocking error
    # it must resolve before continuing (PostToolUse convention). A missing
    # `lizard` install (notices-only) or mode=warn always exits 0.
    return 2 if blocking else 0


def _collect_targets(target):
    """The file itself, or every file beneath it when target is a directory.
    Filtering happens later in should_skip, so this stays a plain walk."""
    if not os.path.isdir(target):
        return [target]
    return [
        os.path.join(root, name)
        for root, _, files in os.walk(target)
        for name in files
    ]


def run_as_report(target):
    """--report entrypoint: print findings for a file or tree. Returns 1 if any
    real finding was printed, 0 otherwise — notices alone are not a failure."""
    any_findings = False
    for path in _collect_targets(target):
        thresholds = load_thresholds(os.path.dirname(path) or ".")
        if should_skip(path, thresholds):
            continue
        findings, notices = analyze_file(path, thresholds)
        if not (findings or notices):
            continue
        any_findings = any_findings or bool(findings)
        print(format_report(path, findings, notices))
        print()
    return 1 if any_findings else 0


if __name__ == "__main__":
    if "--report" in sys.argv:
        args = [a for a in sys.argv[1:] if a != "--report"]
        sys.exit(run_as_report(args[0] if args else "."))
    else:
        sys.exit(run_as_hook())
